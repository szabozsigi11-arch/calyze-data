"""A devizapárok listája (`docs/fx-univerzum.md`, 3. és 7.).

Szabályból áll elő, nem kézi válogatásból:
- a nyolc fő deviza összes párja (28, 2026-10-02);
- az EKB 20 további, nem rögzített árfolyamú devizája az euró, a dollár, a
  font, a frank és a jen ellen (100, 2026-10-19). Az euró és a dollár elleni
  pár a fő deviza-rekordba tartozik; a font, a frank és a jen elleni
  keresztpár (`fx_cross`) saját mérési családba, mert nagyrészt két másik pár
  különbsége, és hamisan növelné a fő rekord mintaszámát.

A fájl egyszer generálódik; utána az azonosítók változatlanok (teszt őrzi).

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
#: Az EKB további devizái 2026-10-19-én: a megszűnt (euróra váltott, a rubel)
#: és a rögzített árfolyamú (DKK, BGN, HKD) kimarad (`docs/fx-univerzum.md`, 7.).
EXTRA = {
    "CZK": "Czech koruna",
    "HUF": "Hungarian forint",
    "PLN": "Polish zloty",
    "RON": "Romanian leu",
    "SEK": "Swedish krona",
    "NOK": "Norwegian krone",
    "ISK": "Icelandic krona",
    "TRY": "Turkish lira",
    "CNY": "Chinese yuan",
    "SGD": "Singapore dollar",
    "KRW": "South Korean won",
    "INR": "Indian rupee",
    "IDR": "Indonesian rupiah",
    "MYR": "Malaysian ringgit",
    "PHP": "Philippine peso",
    "THB": "Thai baht",
    "ILS": "Israeli shekel",
    "MXN": "Mexican peso",
    "BRL": "Brazilian real",
    "ZAR": "South African rand",
}
#: Amelyik fő deviza ellen; a jen piaci szokás szerint a jegyzés oldalán áll
#: (TRY/JPY), a többi az alap oldalán (EUR/HUF).
EXTRA_MAJORS = ("EUR", "USD", "GBP", "CHF", "JPY")
MAIN_SEGMENT_MAJORS = ("EUR", "USD")
FIRST_ID = 671
EXTRA_FIRST_ID = 706
SELECTED_ON = "2026-10-02"
EXTRA_SELECTED_ON = "2026-10-19"
OUT = Path(__file__).resolve().parents[1] / "universe" / "instruments_fx.csv"


def pairs() -> list[tuple[str, str]]:
    return [(a, b) for i, a in enumerate(PRIORITY) for b in PRIORITY[i + 1 :]]


def extra_pairs() -> list[tuple[str, str, str]]:
    """(alap, jegyzett, szegmens) a további devizákra, devizánként a fő devizák sorrendjében."""
    out = []
    for code in EXTRA:
        for major in EXTRA_MAJORS:
            base, quote = (code, major) if major == "JPY" else (major, code)
            out.append((base, quote, "fx" if major in MAIN_SEGMENT_MAJORS else "fx_cross"))
    return out


def _row(k: int, base: str, quote: str, segment: str, selected_on: str) -> dict[str, str]:
    names = NAMES | EXTRA
    return {
        "instrument_id": f"CZ{k:05d}",
        "ticker": f"{base}{quote}",
        "name": f"{names[base]} / {names[quote]}",
        "asset_class": "fx",
        "sector": "",
        "exchange_calendar": "TARGET",
        "valid_from": selected_on,
        "valid_to": "",
        "segment": segment,
        "source_symbol": f"{base}/{quote}",
    }


def build() -> pd.DataFrame:
    rows = [_row(FIRST_ID + k, b, q, "fx", SELECTED_ON) for k, (b, q) in enumerate(pairs())]
    rows += [
        _row(EXTRA_FIRST_ID + k, b, q, seg, EXTRA_SELECTED_ON) for k, (b, q, seg) in enumerate(extra_pairs())
    ]
    return pd.DataFrame(rows)


if __name__ == "__main__":
    build().to_csv(OUT, index=False)
    print(f"{len(build())} pár → {OUT}")
