"""Az aréna-futás kimenete nem mondhat többet, mint amennyit mértünk."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from pipeline.arena.run import build_tables, display_payload, with_regime


def walk(instrument: str, days: int = 700, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, days)))
    return pd.DataFrame(
        {
            "instrument_id": instrument,
            "date": [date(2021, 1, 1) + timedelta(days=i) for i in range(days)],
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000.0,
        }
    )


def prices_frame(count: int = 4) -> pd.DataFrame:
    return pd.concat([walk(f"CZ{i:05d}", seed=i) for i in range(1, count + 1)], ignore_index=True)


def regime_frame(prices: pd.DataFrame) -> pd.DataFrame:
    days = sorted(set(prices["date"]))
    labels = ["calm" if i % 3 else "stressed" for i in range(len(days))]
    return pd.DataFrame({"date": days, "regime": labels})


def test_a_jelzes_megkapja_a_nap_rezsimjet() -> None:
    prices = prices_frame(2)
    from pipeline.arena.signals import all_signals

    signals = with_regime(all_signals(prices), regime_frame(prices))
    assert "regime" in signals.columns
    assert signals["regime"].notna().any()


def test_a_rezsimenkenti_bontas_kulon_mintaszamot_ad() -> None:
    """A rezsim-szűrő csak akkor őszinte, ha a mintaszám is rezsimenként számol."""
    prices = prices_frame()
    _, results = build_tables(prices, regime_frame(prices))

    assert "all" in set(results["regime"])
    assert len(set(results["regime"])) > 1
    for _, group in results.groupby(["rule", "horizon"]):
        total = group[group["regime"] == "all"]["n"]
        parts = group[group["regime"] != "all"]["n"]
        if not total.empty and not parts.empty:
            # A részek összege nem lehet több az összesnél.
            assert parts.sum() <= total.iloc[0]


def test_a_csomag_hordozza_a_tulelesi_torzitast() -> None:
    """A figyelmeztetés nem a felületen él, hanem az adatban — el se lehessen hagyni."""
    prices = prices_frame(2)
    signals, results = build_tables(prices, None)
    payload = display_payload(results, signals, datetime(2026, 9, 25, tzinfo=UTC))

    assert payload["survivorship_bias"] is True
    assert payload["measured_from"] is not None
    assert payload["signals_total"] == len(signals)


def test_minden_sor_mellett_ott_a_baseline_es_a_mintaszam() -> None:
    """Az 1. és 2. sarokkő az arénára is érvényes."""
    prices = prices_frame(3)
    signals, results = build_tables(prices, None)
    payload = display_payload(results, signals, datetime(2026, 9, 25, tzinfo=UTC))

    assert payload["rows"]
    for row in payload["rows"]:
        assert "baseline" in row
        assert row["baseline"] is not None
        assert row["n"] >= 0
        assert row["verdict"] in {
            "better_significant",
            "better_not_significant",
            "same",
            "worse",
            "too_early",
        }
