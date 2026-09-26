"""A minta-aréna futása: a bontások külön sorok, és a csomag nem hallgat el semmit."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from pipeline.patterns.run import build, directions_of, display_payload


def walk(instrument: str, days: int = 900, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, days)))
    noise = rng.uniform(0.002, 0.02, days)
    return pd.DataFrame(
        {
            "instrument_id": instrument,
            "date": [date(2020, 1, 1) + timedelta(days=i) for i in range(days)],
            "open": close * (1 + rng.normal(0, 0.005, days)),
            "high": close * (1 + noise),
            "low": close * (1 - noise),
            "close": close,
            "volume": 1_000_000.0,
        }
    )


def prices() -> pd.DataFrame:
    return pd.concat([walk(f"CZ{i:05d}", seed=i) for i in range(1, 5)], ignore_index=True)


def test_egy_szabalynak_egy_iranya_van() -> None:
    bad = pd.DataFrame({"rule": ["x", "x"], "direction": ["long", "short"]})
    with pytest.raises(RuntimeError, match="Kétirányú"):
        directions_of(bad)


def test_a_bontasok_kulon_sorok() -> None:
    signals, results = build(prices())
    rules = set(signals["rule"])
    # A gyertyamintáknál az összesítés és a kontextus-bontás is megvan.
    candle = [r for r in rules if "|" not in r and not r.startswith(("sr_", "hs_"))]
    assert candle, "véletlen bolyongáson is kell lennie gyertyamintának"
    name = candle[0]
    assert {f"{name}|at_level", f"{name}|none"} & rules
    # A váll-fej-vállnál csak állapot-bontás van, összesítés nincs.
    assert not {"hs_top", "hs_bottom"} & rules
    assert not results.empty


def test_a_csomag_hordozza_a_szotarat_es_a_torzitast() -> None:
    signals, results = build(prices())
    payload = display_payload(results, signals, datetime(2026, 9, 26, tzinfo=UTC))
    assert payload["survivorship_bias"] is True
    assert payload["synonyms"]["tower top"] == "evening_star"
    assert "piercing_line" in payload["low_reliability"]
    for row in payload["rows"]:
        assert row["baseline"] is not None
        assert row["variant"]


def test_a_parhuzamos_futas_ugyanazt_adja() -> None:
    """A párhuzamosítás gyorsít, de az eredményen nem változtathat."""
    data = pd.concat([walk(f"CZ{i:05d}", seed=i) for i in range(1, 10)], ignore_index=True)
    serial, _ = build(data, workers=1)
    parallel, _ = build(data, workers=2)
    pd.testing.assert_frame_equal(serial.reset_index(drop=True), parallel.reset_index(drop=True))
