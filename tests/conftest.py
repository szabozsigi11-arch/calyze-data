from __future__ import annotations

from datetime import date

import pandas as pd
import pytest


def price_rows(ticker: str, days: list[date], base: float = 100.0) -> pd.DataFrame:
    """Szintetikus, hibátlan napi sorok egy tickerre."""
    rows = []
    for i, d in enumerate(days):
        c = base + i
        rows.append(
            {
                "ticker": ticker,
                "date": pd.Timestamp(d),
                "open": c - 0.5,
                "high": c + 1,
                "low": c - 1,
                "close": c,
                "adj_close": c * 0.98,
                "volume": 1_000_000.0,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def sessions_sep_2026() -> list[date]:
    from pipeline.calendar import sessions

    return sessions(date(2026, 9, 1), date(2026, 9, 18))
