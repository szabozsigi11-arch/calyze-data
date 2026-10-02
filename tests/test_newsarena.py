"""Hír-aréna (`docs/hir-arena.md`).

A legfontosabb: a vektoros, egész idősoros számítás minden napra ugyanazt a
jelet adja, mint a napi detektor. Ha eltérne, a backtest nem „ugyanazzal a
szabállyal” készülne, ahogy a definíció ígéri.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from pipeline.newsarena.signals import calendar_days, instrument_frame, market_frame
from pipeline.shocks.detect import instrument_signals, market_signals

TICKERS = ["SPY", "TLT", "GLD", "USO", "UUP", "AAA", "BBB", "CCC"]


@pytest.fixture(scope="module")
def market() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(11)
    days = pd.bdate_range("2024-01-02", periods=180).date
    frames = []
    shock_days = {60, 61, 120}
    for k in range(len(TICKERS)):
        r = rng.normal(0, 0.01, len(days))
        for d in shock_days:
            r[d] += rng.choice([-1, 1]) * 0.06 * (1 + (k % 3))  # néhány nagy mozgás, hogy legyen jel
        close = 100 * np.exp(np.cumsum(r))
        open_ = close * np.exp(rng.normal(0, 0.004, len(days)))
        volume = rng.lognormal(13, 0.3, len(days))
        volume[[60, 130]] *= 6
        frames.append(
            pd.DataFrame(
                {
                    "instrument_id": f"CZ{k:05d}",
                    "date": days,
                    "open": open_,
                    "high": np.maximum(open_, close) * 1.002,
                    "low": np.minimum(open_, close) * 0.998,
                    "close": close,
                    "volume": volume,
                }
            )
        )
    prices = pd.concat(frames, ignore_index=True)
    # Kevesebb múlt az egyik papírnál: a „legalább 22 sor” határt is nézzük.
    prices = prices[~((prices["instrument_id"] == "CZ00007") & (prices["date"] < days[100]))]
    actions = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])
    universe = pd.DataFrame({"ticker": TICKERS, "instrument_id": [f"CZ{k:05d}" for k in range(len(TICKERS))]})
    vix = pd.Series(18 + rng.normal(0, 0.5, len(days)), index=pd.to_datetime(days))
    vix.iloc[[61, 120]] *= 1.35
    macro = pd.DataFrame({"vix": vix})
    return prices, actions, universe, macro


@pytest.mark.parametrize("i", [25, 60, 61, 100, 121, 122, 130, 150])
def test_a_papir_jel_napra_pontosan_a_detektore(market, i: int) -> None:
    prices, actions, _, _ = market
    days = sorted(prices["date"].unique())
    session = days[i]
    expected = instrument_signals(prices, actions, session)
    expected = {r.instrument_id: r.signals != "" for r in expected.itertuples()}
    frame = instrument_frame(prices, actions)
    got = frame[frame["date"] == session].set_index("instrument_id")["flag"].to_dict()
    # A detektor csak a 22 sornál hosszabb múltú papírt adja vissza; ahol nincs, ott nálunk sincs jel.
    for instrument, flag in got.items():
        assert flag == expected.get(instrument, False), (session, instrument)


@pytest.mark.parametrize("i", [30, 60, 61, 120, 121, 150])
def test_a_piaci_jel_napra_pontosan_a_detektore(market, i: int) -> None:
    prices, actions, universe, macro = market
    days = sorted(prices["date"].unique())
    session = days[i]
    signals, _, cross = market_signals(prices, actions, universe, macro, session)
    frame = market_frame(instrument_frame(prices, actions), universe, macro)
    row = frame.loc[session]
    assert bool(row["vix"]) == ("vix" in signals)
    assert bool(row["cross"]) == ("cross_market" in signals)
    assert int(row["cross_count"]) == len(cross)
    assert bool(row["withheld"]) == ("vix" in signals and "cross_market" in signals)


def test_a_kimenetel_a_jelzes_utani_ot_nap(market) -> None:
    prices, actions, _, _ = market
    frame = instrument_frame(prices, actions)
    one = frame[frame["instrument_id"] == "CZ00001"].reset_index(drop=True)
    r = np.log(prices[prices["instrument_id"] == "CZ00001"]["close"].to_numpy())
    r = np.diff(r)
    t = 50  # sor index; a hozam-tömbben a t. sor hozama r[t-1]
    assert one.loc[t, "vol_after"] == pytest.approx(np.std(r[t : t + 5], ddof=1))
    assert one.loc[t, "sigma_before"] == pytest.approx(np.std(r[t - 21 : t - 1], ddof=1))
    # a végén nincs öt jövőbeli nap: nincs kimenetel
    assert np.isnan(one["vol_after"].iloc[-1])


def test_a_naptari_jelzes_az_esemeny_elotti_nap() -> None:
    sessions = list(pd.bdate_range("2026-01-02", "2026-03-31").date)
    flagged = calendar_days(sessions)
    # 2026-01-09 péntek (NFP): az előtte lévő kereskedési nap 01-08
    assert "nfp" in flagged[date(2026, 1, 8)]
    assert all(d in sessions for d in flagged)


def test_a_tesztnapokon_tenyleg_van_jelzes(market) -> None:
    """Ha egyik tesztnapon sincs jel, az egyezés semmit nem bizonyítana."""
    prices, actions, universe, macro = market
    days = sorted(prices["date"].unique())
    frame = instrument_frame(prices, actions)
    assert frame[frame["date"] == days[60]]["flag"].any()
    assert not frame[frame["date"] == days[25]]["flag"].all()
    m = market_frame(frame, universe, macro)
    assert m["vix"].any()
    assert m["cross"].any()


# ---------------------------------------------------------------- mérés


def _instruments(days: int = 200) -> pd.DataFrame:
    """Papír-napok, ahol a jelzett sorok utána tényleg mozgékonyabbak."""
    rng = np.random.default_rng(4)
    rows = []
    start = pd.bdate_range("2025-01-02", periods=days).date
    for i in range(20):
        for d in start:
            flag = rng.random() < 0.1
            before = 0.01
            after = 0.02 if flag else rng.choice([0.008, 0.012])
            rows.append(
                {
                    "instrument_id": f"CZ{i}",
                    "date": d,
                    "flag": flag,
                    "sigma_before": before,
                    "vol_after": after,
                }
            )
    return pd.DataFrame(rows)


def test_a_papir_jel_az_aznapi_jel_nelkuliekhez_mer() -> None:
    from pipeline.newsarena.run import instrument_comparison

    c = instrument_comparison(_instruments())
    assert c is not None
    assert c.value == 1.0  # minden jelzett sor után nagyobb lett a mozgás
    assert 0.4 < c.baseline_value < 0.6  # a jel nélküliek fele-fele
    assert c.n == int(_instruments()["flag"].sum())


def test_a_backtest_es_az_elo_kulon_csalad() -> None:
    from pipeline.newsarena.run import LIVE_FROM, measure

    inst = _instruments(400)
    market_days = sorted(inst["date"].unique())
    market = pd.DataFrame(
        {
            "sigma_before": 0.01,
            "vol_after": [0.02 if k % 7 == 0 else 0.009 for k in range(len(market_days))],
            "market_flag": [k % 7 == 0 for k in range(len(market_days))],
            "withheld": [k % 21 == 0 for k in range(len(market_days))],
        },
        index=market_days,
    )
    live_i = inst[inst["date"] >= LIVE_FROM]
    live_m = market[[d >= LIVE_FROM for d in market.index]]
    table = measure(inst, market, {}, (live_i, live_m))
    assert set(table["period"]) <= {"backtest", "live"}
    for period, part in table.groupby("period"):
        assert (part["n_tests"] == len(part)).all(), period
    back = table[table["period"] == "backtest"].set_index("signal")
    assert back.loc["market_shock", "value"] == 1.0
