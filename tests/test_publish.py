"""A megjelenítési csomag nem mondhat többet, mint amennyit mértünk."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from pipeline.model.evaluate import MIN_OBSERVATIONS
from pipeline.publish.run import (
    HISTORY_SESSIONS,
    HONESTY_MAX_Z,
    HONESTY_MIN_Z,
    HONESTY_WINDOW,
    _uncertainty,
    build_arena,
    build_honesty,
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


def walk_frame(instrument: str, days: int = 600, seed: int = 1) -> pd.DataFrame:
    """Bolyongó árfolyam. Az egyenes vonalú minta nem jó az őszinteség-kapura:
    ott a kimenetel nem bizonytalan, és a válogatás jogosan dobja el."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0004, 0.015, days)
    close = 100.0 * np.exp(np.cumsum(steps))
    dates = pd.bdate_range("2024-01-02", periods=days).date
    return pd.DataFrame(
        {
            "instrument_id": instrument,
            "date": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
        }
    )


def honesty_prices(count: int = 8) -> pd.DataFrame:
    return pd.concat([walk_frame(f"CZ{i:05d}", seed=i) for i in range(1, count + 1)])


def test_az_oszinteseg_kapu_kerdesei_rejtik_a_papirt() -> None:
    """A kérdésben nem lehet benne a papír neve és a dátum (spec/02, F7)."""
    questions = build_honesty(honesty_prices(), date(2026, 9, 18), count=4)
    assert len(questions) == 4
    for q in questions:
        assert set(q.keys()) == {"id", "series", "horizon", "outcome_up", "outcome_return"}
        assert len(q["series"]) == HONESTY_WINDOW
        # A sorozat a legutolsó ponton 100-ra van normálva: a szintből sem
        # lehet visszakeresni, melyik papírról van szó.
        assert q["series"][-1] == 100.0


def test_ugyanarra_a_napra_ugyanazok_a_kerdesek() -> None:
    prices = honesty_prices()
    first = build_honesty(prices, date(2026, 9, 18), count=4)
    again = build_honesty(prices, date(2026, 9, 18), count=4)
    assert first == again


def test_a_kerdeskeszlet_kiegyensulyozott() -> None:
    """Fele emelkedő, fele csökkenő — különben a „mindig felfelé” megnyeri."""
    questions = build_honesty(honesty_prices(12), date(2026, 9, 18), count=6)
    assert len(questions) == 6
    ups = sum(1 for q in questions if q["outcome_up"])
    assert ups == 3


def test_a_trivialis_kerdes_kimarad() -> None:
    """Egyenletesen emelkedő vonalnál a kimenetel nem bizonytalan: nincs kérdés."""
    straight = pd.concat([prices_frame(400), prices_frame(400).assign(instrument_id="CZ00002")])
    assert build_honesty(straight, date(2026, 9, 18), count=4) == []


def test_a_kimenetel_a_bizonytalansagi_savba_esik() -> None:
    """Se zaj, se sokk: a jövőbeli mozgás az ablak saját szórásához mérve."""
    questions = build_honesty(honesty_prices(12), date(2026, 9, 18), count=6)
    for q in questions:
        window = np.array(q["series"], dtype="float64")
        z = _uncertainty(window, float(q["outcome_return"]))
        assert z is not None
        assert HONESTY_MIN_Z <= z <= HONESTY_MAX_Z


def test_a_csomag_kiirja_ha_a_forras_lemaradt() -> None:
    """A felhasználó ne abból jöjjön rá, hogy a dátum ismerősnek tűnik."""
    universe = pd.DataFrame([{"instrument_id": "CZ00001", "ticker": "AAPL", "name": "Apple Inc."}])
    common = {
        "universe": universe,
        "today_forecasts": forecasts_frame(),
        "all_forecasts": forecasts_frame(),
        "outcomes": pd.DataFrame(),
        "arena_records": [],
        "regime": None,
    }
    # 2026-09-22 kedd este: az utolsó zárt nap a 22-e, az adat a 18-ai péntek.
    behind = build_latest(
        session=date(2026, 9, 18),
        now=pd.Timestamp("2026-09-22T23:00:00+00:00").to_pydatetime(),
        **common,
    )
    assert behind["source_lag_sessions"] == 2

    current = build_latest(
        session=date(2026, 9, 22),
        now=pd.Timestamp("2026-09-22T23:00:00+00:00").to_pydatetime(),
        **common,
    )
    assert current["source_lag_sessions"] == 0


def test_a_munkaasztal_idosora_oszlopos_es_eleg_hosszu() -> None:
    """Öt év látható ablak + 200 nap bemelegítés, oszloponként egy tömb."""
    from pipeline.publish.run import WORKBENCH_SESSIONS, build_history

    history = build_history(prices_frame(WORKBENCH_SESSIONS + 100))
    assert set(history) == {"d", "o", "h", "l", "c", "v"}
    lengths = {len(values) for values in history.values()}
    assert lengths == {WORKBENCH_SESSIONS}, "minden oszlop ugyanolyan hosszú"
    # A 200 napos átlagnak az ötéves ablak első napján is léteznie kell.
    assert WORKBENCH_SESSIONS >= 5 * 252 + 200


def test_a_rovid_multu_papir_idosora_nem_potol_semmit() -> None:
    """Ha kevesebb nap van, kevesebb megy ki — nem töltünk fel kitalált sorokkal."""
    from pipeline.publish.run import build_history

    history = build_history(prices_frame(40))
    assert len(history["d"]) == 40
