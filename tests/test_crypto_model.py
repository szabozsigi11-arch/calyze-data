"""Kripto feature-ök, rezsim-kosár és napi becslés (`docs/kripto-modell.md`)."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pipeline.crypto.features import (
    REGIME_BASKET,
    add_crypto_cross_sectional,
    add_macro_asof,
)
from pipeline.crypto.forecast import choose_day, too_late
from pipeline.universe import load_crypto_universe


def test_a_rezsim_kosar_a_rangsor_szerinti_elso_tiz_regi_papir():
    u = load_crypto_universe()
    ranks = {t: i for i, t in enumerate(u["ticker"])}
    assert REGIME_BASKET[0] == "BTC-USD"
    assert len(REGIME_BASKET) == 10
    # A kosár a rangsor sorrendjében áll (nem kézi válogatás).
    assert [ranks[t] for t in REGIME_BASKET] == sorted(ranks[t] for t in REGIME_BASKET)


def test_btc_rel_es_breadth_az_aznapi_ertekekbol():
    u = pd.DataFrame({"instrument_id": ["CZ00621", "CZ00622"], "ticker": ["BTC-USD", "ETH-USD"]})
    d = date(2026, 9, 1)
    feats = pd.DataFrame(
        {
            "instrument_id": ["CZ00621", "CZ00622"],
            "date": [d, d],
            "ret_20": [0.10, 0.25],
            "ema_dist_50": [0.02, -0.01],
        }
    )
    out = add_crypto_cross_sectional(feats, u).set_index("instrument_id")
    assert out.loc["CZ00621", "btc_rel_20"] == pytest.approx(0.0)
    assert out.loc["CZ00622", "btc_rel_20"] == pytest.approx(0.15)
    assert out.loc["CZ00622", "breadth_50"] == pytest.approx(0.5)


def test_a_makro_hetvegen_a_penteki_erteket_viszi_legfeljebb_5_napig():
    fridays = pd.DataFrame(
        {"vix": [20.0] * 30, "yield_10y": 4.0, "yield_curve_10y2y": 0.5, "dollar_index": 100.0},
        index=[date(2026, 7, 1) + timedelta(days=i) for i in range(30)],
    )
    # 07-30 után nincs makro-sor: 08-04-ig (5 nap) még töltődik, 08-05-én már nem.
    feats = pd.DataFrame({"instrument_id": "CZ00621", "date": [date(2026, 8, 4), date(2026, 8, 5)]})
    out = add_macro_asof(feats, fridays)
    assert out["vix"].iloc[0] == 20.0
    assert np.isnan(out["vix"].iloc[1])


def test_a_legfrissebb_eleg_lefedett_napot_valasztja():
    cov = {date(2026, 10, 1): 10, date(2026, 9, 30): 50}
    assert choose_day(cov, date(2026, 10, 1), 50) == date(2026, 9, 30)
    with pytest.raises(RuntimeError):
        choose_day({date(2026, 9, 25): 50}, date(2026, 10, 1), 50)


def test_a_zaras_utan_6_orannal_kesobbi_becsles_nem_szamit():
    from datetime import UTC, datetime

    day = date(2026, 10, 2)  # zár: 10-03 00:00 UTC
    assert not too_late(day, datetime(2026, 10, 3, 0, 30, tzinfo=UTC))
    assert not too_late(day, datetime(2026, 10, 3, 5, 59, tzinfo=UTC))
    assert too_late(day, datetime(2026, 10, 3, 6, 1, tzinfo=UTC))


def test_kripto_sokk_res_nelkul_es_kosar_jel():
    from pipeline.crypto.shocks import BROAD_MIN, attach

    days = [date(2026, 7, 1) + timedelta(days=i) for i in range(70)]
    rng = np.random.default_rng(1)
    u = pd.DataFrame({"instrument_id": [f"CZ{621 + i:05d}" for i in range(10)], "ticker": REGIME_BASKET})
    rows = []
    for k, iid in enumerate(u["instrument_id"]):
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
        # Az utolsó napon a kosár fele nagyot mozdul, a nyitás pedig „rést” hagy.
        if k < BROAD_MIN:
            close[-1] = close[-2] * 1.2
        for d, c in zip(days, close, strict=True):
            rows.append(
                {
                    "instrument_id": iid,
                    "date": d,
                    "open": c * 0.8,
                    "high": c,
                    "low": c,
                    "close": c,
                    "volume": 1e6,
                }
            )
    prices = pd.DataFrame(rows)
    frame = pd.DataFrame({"instrument_id": list(u["instrument_id"])})
    out = attach(frame, prices, u, days[-1]).set_index("instrument_id")
    assert set(out["shock_market"]) == {"crypto_broad"}
    assert out.loc["CZ00621", "shock_signals"] == "move"  # a rés-jel nem szól, a 24/7-es piacon nincs rés
    assert out.loc["CZ00630", "shock_signals"] == ""
    assert not out["withheld"].any()


def test_kripto_hir_arena_kosar_jel_es_res_nelkul():
    from pipeline.crypto.arenas import crypto_frames
    from pipeline.crypto.shocks import BROAD_MIN

    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(90)]
    rng = np.random.default_rng(3)
    u = pd.DataFrame({"instrument_id": [f"CZ{621 + i:05d}" for i in range(10)], "ticker": REGIME_BASKET})
    rows = []
    for k, iid in enumerate(u["instrument_id"]):
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
        if k < BROAD_MIN:
            close[70:] *= 1.25  # egy napon a kosár fele nagyot mozdul
        for d, c in zip(days, close, strict=True):
            rows.append(
                {
                    "instrument_id": iid,
                    "date": d,
                    "open": c * 0.7,
                    "high": c,
                    "low": c,
                    "close": c,
                    "volume": 1e6,
                }
            )
    inst, market = crypto_frames(pd.DataFrame(rows), u)
    assert bool(market.loc[days[70], "market_flag"])
    assert not market["withheld"].any()
    # A „rés” (nyitás 30%-kal a záró alatt) kriptón nem jel: ami jelzett, azt
    # mozgás vagy volumen okozta, és a nagy rés önmagában nem ad jelet.
    flagged = inst[inst["flag"]]
    assert ((flagged["move_sigma"] > 2.5) | (flagged["volume_z"] > 3)).all()
    assert (inst["gap_sigma"] > 2).any()
