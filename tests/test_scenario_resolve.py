"""A rögzített forgatókönyvek napi feldolgozása: pin a lenyomatból, lezárás a sokk-jelekből."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from pipeline.scenario.calibrate import QUANTILE_LEVELS
from pipeline.scenario.resolve import Entry, condition_held, pin_entries, resolve_entries

DAYS = [date(2026, 10, d) for d in (19, 20, 21, 22, 23)]

CALIBRATION = {
    "quantile_levels": [float(v) for v in QUANTILE_LEVELS],
    "horizons": {
        "1": {
            r: {"quantiles": list(np.linspace(-2, 2, 199)), "band_q": 1.5, "calm_windows": 500}
            for r in ("all", "calm", "normal", "stressed")
        }
    },
}


def packages(shock_on: date | None = None) -> pd.DataFrame:
    rows = []
    for d in DAYS:
        rows.append(
            {
                "instrument_id": "CZ00001",
                "session": d,
                "horizon": 1,
                "made_at": pd.Timestamp(datetime(d.year, d.month, d.day, 22, 40, tzinfo=UTC)),
                "expected_return": 0.01,
                "scale": 0.02,
                "baseline_prob": 0.52,
                "regime": "normal",
                "target_session": DAYS[min(DAYS.index(d) + 1, len(DAYS) - 1)],
                "withheld": False,
                "shock_status": "ok",
                "shock_signals": "move" if d == shock_on else "",
                "shock_market": "",
            }
        )
    return pd.DataFrame(rows)


def entry(**kw: object) -> Entry:
    base = {
        "id": "e1",
        "instrument_id": "CZ00001",
        "horizon": 1,
        "assumed_regime": "today",
        "created_at": datetime(2026, 10, 20, 15, 0, tzinfo=UTC),
        "pinned": False,
        "prob_up": None,
        "baseline_prob": None,
        "forecast_session": None,
        "target_session": None,
    }
    return Entry(**(base | kw))  # type: ignore[arg-type]


def test_a_pin_a_rogzites_elotti_utolso_lenyomatbol_szamol() -> None:
    pins = pin_entries([entry()], packages(), CALIBRATION)
    row = pins["e1"]
    # 10-20 15:00-kor a 10-19-i (22:40-es) csomag a legutóbbi: a 10-20-i még nem létezett.
    assert row["forecast_session"] == "2026-10-19"
    assert row["regime_used"] == "normal"
    assert 0.5 < float(row["prob_up"]) < 1  # type: ignore[arg-type]
    assert row["band_low"] < 0.01 < row["band_high"]  # type: ignore[operator]
    assert row["baseline_prob"] == 0.52


def test_csomag_nelkul_nincs_szam_es_kalibracio_nelkul_sincs() -> None:
    assert (
        pin_entries([entry(instrument_id="CZ00999")], packages(), CALIBRATION)["e1"]["status"]
        == "no_estimate"
    )
    assert pin_entries([entry()], packages(), None)["e1"]["status"] == "no_estimate"


def test_a_sokk_az_ablakban_nem_teljesult_feltetel() -> None:
    assert condition_held(packages(), "CZ00001", DAYS[0], DAYS[1])
    assert not condition_held(packages(shock_on=DAYS[1]), "CZ00001", DAYS[0], DAYS[1])
    # A becslés napjának jele nem számít (azt a becslés már látta).
    assert condition_held(packages(shock_on=DAYS[0]), "CZ00001", DAYS[0], DAYS[1])


def test_lezaras_csak_teljesult_feltetelnel_pontoz() -> None:
    pinned = entry(
        pinned=True, prob_up=0.6, baseline_prob=0.52, forecast_session=DAYS[0], target_session=DAYS[1]
    )
    series = {"CZ00001": pd.Series([100.0, 101.0, 99.0, 98.0, 97.0], index=DAYS)}
    ok = resolve_entries([pinned], series, packages(), DAYS[-1])["e1"]
    assert ok["status"] == "resolved"
    assert ok["hit"] is True
    assert ok["baseline_hit"] is True
    failed = resolve_entries([pinned], series, packages(shock_on=DAYS[1]), DAYS[-1])["e1"]
    assert failed["status"] == "condition_failed"
    assert "hit" not in failed


def test_a_celnap_elott_nem_zar() -> None:
    pinned = entry(
        pinned=True, prob_up=0.6, baseline_prob=0.5, forecast_session=DAYS[0], target_session=DAYS[3]
    )
    series = {"CZ00001": pd.Series([100.0, 101.0, 99.0, 98.0, 97.0], index=DAYS)}
    assert resolve_entries([pinned], series, packages(), DAYS[2]) == {}
