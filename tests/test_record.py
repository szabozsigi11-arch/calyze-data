"""Eredménynapló (`docs/eredmenynaplo.md`): napi sorok, legrosszabb becslések, havi letöltés."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime

import pandas as pd

from pipeline.ingest.partitions import from_parquet
from pipeline.publish.record import EXPORT_COLUMNS, build_record, daily, enrich, worst

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def outcome(
    i: int, target: date, horizon: int = 5, prob: float = 0.6, up: bool = True, **extra: object
) -> dict:
    hit = float((prob > 0.5) == up)
    y = 1.0 if up else 0.0
    return {
        "forecast_id": f"f{i}",
        "instrument_id": f"CZ{i % 7:03d}",
        "session": date(2026, 9, 1),
        "target_session": target,
        "horizon": horizon,
        "regime": "calm",
        "model_family": "lgbm-core",
        "model_version": "v1",
        "resolved_at": pd.Timestamp(datetime(2026, 9, 30, 2, tzinfo=UTC)),
        "actual_return": 0.01 if up else -0.02,
        "prob_up": prob,
        "baseline_prob": 0.52,
        "hit": hit,
        "baseline_hit": float(up),
        "brier": (prob - y) ** 2,
        "baseline_brier": (0.52 - y) ** 2,
        "covered": 1.0,
        "resolution_type": "normal",
        **extra,
    }


UNIVERSE = pd.DataFrame({"instrument_id": [f"CZ{i:03d}" for i in range(7)], "ticker": list("ABCDEFG")})


def test_napi_sorok_a_lezarasi_nap_szerint() -> None:
    rows = [outcome(i, date(2026, 9, 29), up=i % 3 != 0) for i in range(40)]
    rows += [outcome(100 + i, date(2026, 9, 30)) for i in range(5)]
    data = enrich(pd.DataFrame(rows), pd.DataFrame(), UNIVERSE)
    days = daily(data)["5"]
    assert [d[0] for d in days] == ["2026-09-29", "2026-09-30"]
    # a 30 alatti nap is benne van, a darabszámmal
    assert days[1][1] == 5
    first = days[0]
    assert first[1] == 40
    assert first[2] == sum(1 for i in range(40) if i % 3 != 0)  # a modell mindig emelkedést várt
    assert first[3] == first[2]  # a baseline is 0,52 → ugyanazok


def test_a_legrosszabb_a_magabiztos_tevedes() -> None:
    rows = [
        outcome(1, date(2026, 9, 29), prob=0.55, up=False),
        outcome(2, date(2026, 9, 29), prob=0.90, up=False),
        outcome(3, date(2026, 9, 29), prob=0.70, up=True),
        outcome(4, date(2026, 9, 30), prob=0.90, up=False),
    ]
    data = enrich(pd.DataFrame(rows), pd.DataFrame(), UNIVERSE)
    top = worst(data, per_horizon=3)
    assert [r["target_session"] for r in top[:2]] == ["2026-09-30", "2026-09-29"]  # egyenlőnél az újabb
    assert top[2]["prob_up"] == 0.55
    assert all(r["ticker"] in "ABCDEFG" for r in top)


def test_a_visszatartott_becsles_is_benne_van_jelolve() -> None:
    rows = [outcome(1, date(2026, 9, 29), prob=0.9, up=False), outcome(2, date(2026, 9, 29))]
    forecasts = pd.DataFrame({"forecast_id": ["f1", "f2"], "withheld": [True, False]})
    data = enrich(pd.DataFrame(rows), forecasts, UNIVERSE)
    top = worst(data)
    assert top[0]["withheld"] is True
    assert len(top) == 2


def test_havi_letoltes_csak_ahol_kell() -> None:
    rows = [outcome(i, date(2026, 8, 20)) for i in range(3)]
    rows += [
        outcome(10 + i, date(2026, 9, 29), resolved_at=pd.Timestamp(datetime(2026, 9, 30, tzinfo=UTC)))
        for i in range(4)
    ]
    rows[0]["resolved_at"] = pd.Timestamp(datetime(2026, 8, 21, tzinfo=UTC))
    rows[1]["resolved_at"] = pd.Timestamp(datetime(2026, 8, 21, tzinfo=UTC))
    rows[2]["resolved_at"] = pd.Timestamp(datetime(2026, 8, 21, tzinfo=UTC))
    existing = {
        "record/2026-08.csv",
        "record/2026-08.parquet",
        "record/2026-09.csv",
        "record/2026-09.parquet",
    }
    doc, files = build_record(pd.DataFrame(rows), pd.DataFrame(), UNIVERSE, existing, NOW)

    assert [m["month"] for m in doc["months"]] == ["2026-08", "2026-09"]  # type: ignore[index]
    assert [m["rows"] for m in doc["months"]] == [3, 4]  # type: ignore[index]
    # augusztus régi és megvan: nem megy fel újra; szeptemberbe friss lezárás került
    assert sorted(p for p, _, _ in files) == ["record/2026-09.csv", "record/2026-09.parquet"]

    csv = next(b for p, b, _ in files if p.endswith(".csv"))
    frame = pd.read_csv(io.BytesIO(csv))
    assert list(frame.columns) == EXPORT_COLUMNS
    assert len(frame) == 4
    parquet = next(b for p, b, _ in files if p.endswith(".parquet"))
    assert len(from_parquet(parquet)) == 4


def test_hianyzo_honap_felmegy() -> None:
    rows = [outcome(i, date(2026, 8, 20)) for i in range(3)]
    for r in rows:
        r["resolved_at"] = pd.Timestamp(datetime(2026, 8, 21, tzinfo=UTC))
    _, files = build_record(pd.DataFrame(rows), pd.DataFrame(), UNIVERSE, set(), NOW)
    assert len(files) == 2


def test_ures() -> None:
    doc, files = build_record(pd.DataFrame(), pd.DataFrame(), UNIVERSE, set(), NOW)
    assert doc["resolved"] == 0
    assert files == []
