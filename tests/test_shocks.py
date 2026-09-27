"""A sokk-detektor (docs/sokk-detektor.md)."""

from datetime import date

import numpy as np
import pandas as pd

from pipeline.calendar import sessions
from pipeline.publish.run import _shock, format_forecast
from pipeline.shocks import detect as sd

DAYS = sessions(date(2026, 6, 1), date(2026, 9, 18))
S = DAYS[-1]
BASKET = list(sd.BASKET)
EQUITIES = [f"EQ{i}" for i in range(10)]
NO_ACTIONS = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])


def universe() -> pd.DataFrame:
    rows = [{"instrument_id": t, "ticker": t, "asset_class": "etf", "sector": None} for t in BASKET]
    rows += [{"instrument_id": t, "ticker": t, "asset_class": "equity", "sector": "Tech"} for t in EQUITIES]
    return pd.DataFrame(rows)


def prices(shock: dict[str, float] | None = None, volume: dict[str, float] | None = None) -> pd.DataFrame:
    """Nyugodt, determinisztikus sorok; az utolsó napon `shock` log-hozam, `volume` szorzó."""
    rng = np.random.default_rng(7)
    rows = []
    for inst in BASKET + EQUITIES:
        price = 100.0
        for d in DAYS:
            r = rng.normal(0, 0.01)
            if d == S and shock and inst in shock:
                r = shock[inst]
            prev = price
            price = price * float(np.exp(r))
            v = 1_000_000 * (1 + rng.normal(0, 0.05))
            if d == S and volume and inst in volume:
                v *= volume[inst]
            rows.append({"instrument_id": inst, "date": d, "open": prev, "close": price, "volume": v})
    return pd.DataFrame(rows)


def macro(vix_last: float) -> pd.DataFrame:
    idx = pd.to_datetime(DAYS[-5:])
    return pd.DataFrame({"vix": [15, 15, 15, 15, vix_last]}, index=idx)


def test_nyugodt_napon_nincs_jelzes():
    classified, shock = sd.detect(prices(), NO_ACTIONS, universe(), macro(15.5), S)
    assert shock.signals == ()
    assert not shock.withheld
    assert (classified["signals"] == "").all()


def test_egy_papir_volumen_kiugrasa_papir_szintu_zaj():
    classified, shock = sd.detect(prices(volume={"EQ3": 4.0}), NO_ACTIONS, universe(), macro(15.5), S)
    row = classified.set_index("instrument_id").loc["EQ3"]
    assert row["signals"] == "volume"
    assert row["shock_scope"] == "instrument"
    assert row["shock_persistence"] == "intraday_noise"
    assert not shock.withheld


def test_ot_eszkozosztalybol_harom_es_vix_ugras_visszatartas():
    moves = {"SPY": -0.06, "GLD": 0.05, "USO": 0.08}
    classified, shock = sd.detect(prices(shock=moves), NO_ACTIONS, universe(), macro(21.0), S)
    assert set(shock.signals) == {"vix", "cross_market"}
    assert set(shock.cross) == {"SPY", "GLD", "USO"}
    assert shock.tractability == "unknowable"
    assert shock.withheld
    assert (classified["shock_scope"] == "global_macro").all()


def test_ket_eszkozosztaly_meg_nem_keresztpiaci():
    _, shock = sd.detect(prices(shock={"SPY": -0.06, "GLD": 0.05}), NO_ACTIONS, universe(), macro(15.5), S)
    assert "cross_market" not in shock.signals


def test_vix_ugras_egyedul_global_macro_de_nem_tart_vissza():
    _, shock = sd.detect(prices(), NO_ACTIONS, universe(), macro(19.0), S)
    assert shock.signals == ("vix",)
    assert shock.scope == "global_macro"
    assert not shock.withheld


def test_szektor_szintu_jelzes():
    moves = {t: 0.07 for t in EQUITIES[:4]}
    classified, _ = sd.detect(prices(shock=moves), NO_ACTIONS, universe(), macro(15.5), S)
    row = classified.set_index("instrument_id").loc["EQ0"]
    # 10 tech papírból 4 jelzett (40% ≥ 30%): szektor, és az univerzum 40%-a is → ország
    assert row["shock_scope"] in {"sector", "country"}


def test_felosztas_napjan_nincs_res_jel():
    p = prices()
    p.loc[(p["instrument_id"] == "EQ1") & (p["date"] == S), "open"] = 25.0
    actions = pd.DataFrame([{"instrument_id": "EQ1", "date": S, "dividend": np.nan, "split_ratio": 4.0}])
    classified, _ = sd.detect(p, actions, universe(), macro(15.5), S)
    assert "gap" not in classified.set_index("instrument_id").loc["EQ1", "signals"]


def test_visszatartott_becsles_szam_nelkul_jelenik_meg():
    row = {"horizon": 5, "target_session": S, "prob_up": 0.61, "withheld": True, "shock_status": "ok",
           "shock_signals": "", "shock_market": "vix,cross_market", "shock_scope": "global_macro",
           "shock_persistence": "days", "shock_tractability": "unknowable"}  # fmt: skip
    shown = format_forecast(row)
    assert shown["withheld"] is True
    assert shown["prob_up"] is None
    assert shown["shock"]["market"] == ["vix", "cross_market"]
    assert _shock({"horizon": 5})["status"] == "not_collected"
