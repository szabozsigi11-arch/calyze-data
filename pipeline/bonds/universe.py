"""A 7 kötvény-idősor (`docs/kotveny.md`, 3.). Egyszer generálódik.

Futtatás (egyszer):
    uv run python -m pipeline.bonds.universe
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SERIES = (
    ("UST3M", "US Treasury 3-month yield", "3 Mo"),
    ("UST2Y", "US Treasury 2-year yield", "2 Yr"),
    ("UST5Y", "US Treasury 5-year yield", "5 Yr"),
    ("UST10Y", "US Treasury 10-year yield", "10 Yr"),
    ("UST30Y", "US Treasury 30-year yield", "30 Yr"),
    ("UST10Y2Y", "US Treasury 10-year minus 2-year spread", "10 Yr-2 Yr"),
    ("UST30Y5Y", "US Treasury 30-year minus 5-year spread", "30 Yr-5 Yr"),
)
FIRST_ID = 699
OUT = Path(__file__).resolve().parents[1] / "universe" / "instruments_bonds.csv"


def build() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "instrument_id": f"CZ{FIRST_ID + k:05d}",
                "ticker": ticker,
                "name": name,
                "asset_class": "bond",
                "sector": "",
                "exchange_calendar": "UST",
                "valid_from": "2026-10-03",
                "valid_to": "",
                "segment": "bond",
                "source_symbol": source,
            }
            for k, (ticker, name, source) in enumerate(SERIES)
        ]
    )


if __name__ == "__main__":
    build().to_csv(OUT, index=False)
    print(f"{len(build())} idősor → {OUT}")
