"""A kötvény-idősorok (`docs/kotveny.md`, 3. és 10.). Egyszer generálódik.

Az első 7 (2026-10-03) azonosítója soha nem változik; a bővítés (2026-10-19)
a teljes deviza-lista után, 806-tól folytatódik.

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
#: 2026-10-19: a nominális görbe további futamidejei, a reálhozam (TIPS) és a
#: 10 éves inflációs várakozás (nominális mínusz reál, „breakeven”).
EXTRA_SERIES = (
    ("UST1M", "US Treasury 1-month yield", "1 Mo"),
    ("UST6M", "US Treasury 6-month yield", "6 Mo"),
    ("UST1Y", "US Treasury 1-year yield", "1 Yr"),
    ("UST3Y", "US Treasury 3-year yield", "3 Yr"),
    ("UST7Y", "US Treasury 7-year yield", "7 Yr"),
    ("UST20Y", "US Treasury 20-year yield", "20 Yr"),
    ("TIPS5Y", "US Treasury 5-year real yield (TIPS)", "Real 5 YR"),
    ("TIPS10Y", "US Treasury 10-year real yield (TIPS)", "Real 10 YR"),
    ("TIPS30Y", "US Treasury 30-year real yield (TIPS)", "Real 30 YR"),
    ("UST10YBE", "US 10-year breakeven inflation (nominal minus real)", "10 Yr-Real 10 YR"),
)
FIRST_ID = 699
EXTRA_FIRST_ID = 806
OUT = Path(__file__).resolve().parents[1] / "universe" / "instruments_bonds.csv"


def _row(k: int, ticker: str, name: str, source: str, selected_on: str) -> dict[str, str]:
    return {
        "instrument_id": f"CZ{k:05d}",
        "ticker": ticker,
        "name": name,
        "asset_class": "bond",
        "sector": "",
        "exchange_calendar": "UST",
        "valid_from": selected_on,
        "valid_to": "",
        "segment": "bond",
        "source_symbol": source,
    }


def build() -> pd.DataFrame:
    rows = [_row(FIRST_ID + k, *spec, "2026-10-03") for k, spec in enumerate(SERIES)]
    rows += [_row(EXTRA_FIRST_ID + k, *spec, "2026-10-19") for k, spec in enumerate(EXTRA_SERIES)]
    return pd.DataFrame(rows)


if __name__ == "__main__":
    build().to_csv(OUT, index=False)
    print(f"{len(build())} idősor → {OUT}")
