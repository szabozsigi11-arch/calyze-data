"""A megjelenítési csomag nem mondhat többet, mint amennyit mértünk."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from pipeline.model.evaluate import MIN_OBSERVATIONS
from pipeline.publish.run import (
    HISTORY_SESSIONS,
    build_arena,
    build_index,
    build_instrument,
    build_latest,
    headline,
    next_resolutions,
)


def forecasts_frame() -> pd.DataFrame:
    rows = []
    for horizon, target in ((5, date(2026, 9, 25)), (20, date(2026, 10, 16)), (60, date(2026, 12, 11))):
        rows.append(
            {
                "forecast_id": f"f{horizon}",
                "instrument_id": "CZ00001",
                "session": date(2026, 9, 18),
                "horizon": horizon,
                "target_session": target,
                "prob_up": 0.5432,
                "baseline_prob": 0.5101,
                "baseline_id": "naive",
                "expected_return": 0.0041,
                "band_low": -0.05,
                "band_high": 0.06,
                "price_low": 95.0,
                "price_high": 106.0,
                "expected_price": 100.4,
                "made_at": "2026-09-20T06:54:41+00:00",
                "regime": "normal",
                "contributions": json.dumps([{"feature": "mom_20", "value": 0.012}]),
            }
        )
    return pd.DataFrame(rows)


def prices_frame(days: int = 300) -> pd.DataFrame:
    dates = pd.bdate_range("2025-06-02", periods=days).date
    return pd.DataFrame(
        {
            "instrument_id": "CZ00001",
            "date": dates,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": [100.0 + i * 0.1 for i in range(days)],
            "volume": 1_000_000,
        }
    )


def test_a_chart_legfeljebb_a_megadott_hosszusagu() -> None:
    payload = build_instrument(
        meta={"id": "CZ00001", "ticker": "AAPL", "name": "Apple Inc."},
        prices=prices_frame(),
        forecasts=forecasts_frame(),
        history=forecasts_frame().rename(columns={"session": "session"}),
        outcomes=pd.DataFrame(),
        session=date(2026, 9, 18),
    )
    assert len(payload["candles"]) == HISTORY_SESSIONS
    assert payload["candles"][-1]["d"] > payload["candles"][0]["d"]


def test_a_becsles_minden_horizontra_kimegy_a_magyarazattal() -> None:
    payload = build_instrument(
        meta={"id": "CZ00001", "ticker": "AAPL", "name": "Apple Inc."},
        prices=prices_frame(),
        forecasts=forecasts_frame(),
        history=pd.DataFrame(columns=["session", "horizon"]),
        outcomes=pd.DataFrame(),
        session=date(2026, 9, 18),
    )
    assert [f["horizon"] for f in payload["forecasts"]] == [5, 20, 60]
    first = payload["forecasts"][0]
    assert first["baseline_prob"] is not None, "baseline nélkül nem mehet ki szám"
    assert first["contributions"][0]["feature"] == "mom_20"


def test_papirszintu_teljesitmeny_csak_mintaszamot_kozol() -> None:
    """Két lezárt megfigyelésből nem lesz százalék (2. sarokkő)."""
    outcomes = pd.DataFrame({"hit": [True, False], "baseline_hit": [True, True]})
    payload = build_instrument(
        meta={"id": "CZ00001", "ticker": "AAPL", "name": "Apple Inc."},
        prices=prices_frame(10),
        forecasts=forecasts_frame(),
        history=pd.DataFrame(columns=["session", "horizon"]),
        outcomes=outcomes,
        session=date(2026, 9, 18),
    )
    assert payload["performance"] == {
        "n": 2,
        "min_observations": MIN_OBSERVATIONS,
        "hits": 1,
        "baseline_hits": 2,
    }
    assert "value" not in payload["performance"]


def test_a_kovetkezo_lezaras_datuma_horizontonkent() -> None:
    result = next_resolutions(forecasts_frame(), pd.DataFrame())
    assert result == {"5": "2026-09-25", "20": "2026-10-16", "60": "2026-12-11"}


def test_a_mar_lezart_becsles_nem_szamit_a_kovetkezo_datumba() -> None:
    outcomes = pd.DataFrame({"forecast_id": ["f5"]})
    result = next_resolutions(forecasts_frame(), outcomes)
    assert result["5"] is None


def test_az_arena_rekordok_atmennek_a_mezonevekkel() -> None:
    arena = pd.DataFrame(
        [
            {
                "subject_id": "lgbm-core v1",
                "scope": "universe",
                "horizon": 20,
                "regime": "all",
                "metric": "direction_accuracy",
                "baseline_id": "naive",
                "value": 0.55,
                "baseline_value": 0.52,
                "delta": 0.03,
                "n": 120,
                "n_eff": 41.2,
                "p_value": 0.04,
                "p_value_fdr": 0.06,
                "n_tests": 18,
                "verdict": "better_not_significant",
                "observations_needed": 340,
                "first_observed": "2026-09-18",
                "last_observed": "2026-10-16",
            }
        ]
    )
    records = build_arena(arena)
    assert records[0]["n"] == 120
    assert records[0]["verdict"] == "better_not_significant"
    assert headline(records) is records[0]


def test_ures_arena_eseten_nincs_verdict() -> None:
    assert build_arena(pd.DataFrame()) == []
    assert headline([]) is None


def test_a_rovid_multu_papir_indokot_kap() -> None:
    universe = pd.DataFrame(
        [
            {"instrument_id": "CZ00001", "ticker": "AAPL", "name": "Apple Inc.", "asset_class": "equity"},
            {"instrument_id": "CZ00999", "ticker": "NEWCO", "name": "New Co.", "asset_class": "equity"},
        ]
    )
    index = build_index(universe, forecasts_frame(), prices_frame(120))
    by_ticker = {row["ticker"]: row for row in index}
    assert by_ticker["AAPL"]["forecastable"] is True
    assert by_ticker["NEWCO"]["forecastable"] is False
    assert by_ticker["NEWCO"]["reason"] == "short_history"


def test_a_napi_osszefoglalo_kiirja_a_kovetkezo_lezarast() -> None:
    universe = pd.DataFrame([{"instrument_id": "CZ00001", "ticker": "AAPL", "name": "Apple Inc."}])
    latest = build_latest(
        session=date(2026, 9, 18),
        universe=universe,
        today_forecasts=forecasts_frame(),
        all_forecasts=forecasts_frame(),
        outcomes=pd.DataFrame(),
        arena_records=[],
        regime=pd.DataFrame([{"date": date(2026, 9, 18), "regime": "normal", "stress": 0.41}]),
        now=pd.Timestamp("2026-09-20T07:00:00+00:00").to_pydatetime(),
    )
    assert latest["regime"] == "normal"
    assert latest["regime_stress"] == 0.41
    assert latest["verdict"] is None, "mérés nélkül nincs verdict"
    assert latest["next_resolution"]["5"] == "2026-09-25"
    assert latest["forecasts_open"] == 3


def test_a_becsles_nelkuli_papir_csomagja_is_elkeszul() -> None:
    """Rövid múltú papírra nincs becslés — ettől még kell a chartja és a fejléce."""
    payload = build_instrument(
        meta={"id": "CZ00999", "ticker": "NEWCO", "name": "New Co."},
        prices=prices_frame(40),
        forecasts=pd.DataFrame(),
        history=pd.DataFrame(),
        outcomes=pd.DataFrame(),
        session=date(2026, 9, 18),
    )
    assert payload["forecasts"] == []
    assert payload["timeline"] == []
    assert payload["regime"] is None
    assert len(payload["candles"]) == 40
