"""A 28 devizapár listája (`docs/fx-univerzum.md`, 3.).

Szabályból áll elő, nem kézi válogatásból: a nyolc fő deviza összes párja,
piaci elnevezéssel. A fájl egyszer generálódik; utána az azonosítók
változatlanok (teszt őrzi).

Futtatás (egyszer):
    uv run python -m pipeline.fx.universe
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

#: Az alap deviza a listában előrébb álló (piaci szokás).
PRIORITY = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY")
NAMES = {
    "EUR": "Euro",
    "GBP": "British pound",
    "AUD": "Australian dollar",
    "NZD": "New Zealand dollar",
    "USD": "US dollar",
    "CAD": "Canadian dollar",
    "CHF": "Swiss franc",
    "JPY": "Japanese yen",
}
FIRST_ID = 671
SELECTED_ON = "2026-10-02"
OUT = Path(__file__).resolve().parents[1] / "universe" / "instruments_fx.csv"


def pairs() -> list[tuple[str, str]]:
    return [(a, b) for i, a in enumerate(PRIORITY) for b in PRIORITY[i + 1 :]]


def build() -> pd.DataFrame:
    rows = []
    for k, (base, quote) in enumerate(pairs()):
        rows.append(
            {
                "instrument_id": f"CZ{FIRST_ID + k:05d}",
                "ticker": f"{base}{quote}",
                "name": f"{NAMES[base]} / {NAMES[quote]}",
                "asset_class": "fx",
                "sector": "",
                "exchange_calendar": "TARGET",
                "valid_from": SELECTED_ON,
                "valid_to": "",
                "segment": "fx",
                "source_symbol": f"{base}/{quote}",
            }
        )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    build().to_csv(OUT, index=False)
    print(f"{len(build())} pár → {OUT}")
