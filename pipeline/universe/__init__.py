"""Az instrumentum-univerzum (spec/01, 7. fejezet; spec/05, 2.5).

Minden instrumentum állandó belső azonosítót kap (`CZ00001`). A ticker csak
megjelenítési név, és idővel változhat (FB → META); a becslés, a tézis és a
trade az azonosítóhoz kötődik. Egy azonosítót soha nem adunk újra ki.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

UNIVERSE_FILE = Path(__file__).with_name("instruments.csv")
ID_PATTERN = re.compile(r"^CZ\d{5}$")
ASSET_CLASSES = {"equity", "etf"}


class UniverseError(ValueError):
    """Az univerzum-fájl hibás; a futás nem indulhat el vele."""


def load_universe(path: Path = UNIVERSE_FILE) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    validate_universe(frame)
    frame["valid_from"] = [date.fromisoformat(v) for v in frame["valid_from"]]
    # Üres `valid_to` = ma is az univerzum része. Python-dátumként tartjuk,
    # mert a pandas a csupa-üres oszlopot dátum helyett időbélyeggé alakítaná.
    valid_to = [date.fromisoformat(v) if v else None for v in frame["valid_to"]]
    frame["valid_to"] = pd.Series(valid_to, dtype=object, index=frame.index)
    return frame


def validate_universe(frame: pd.DataFrame) -> None:
    required = {"instrument_id", "ticker", "name", "asset_class", "sector", "exchange_calendar", "valid_from"}
    missing = required - set(frame.columns)
    if missing:
        raise UniverseError(f"hiányzó oszlopok: {sorted(missing)}")
    bad_ids = [i for i in frame["instrument_id"] if not ID_PATTERN.match(i)]
    if bad_ids:
        raise UniverseError(f"hibás azonosítók: {bad_ids[:5]}")
    if frame["instrument_id"].duplicated().any():
        raise UniverseError("ismétlődő instrument_id")
    active = frame[frame["valid_to"].fillna("") == ""]
    if active["ticker"].duplicated().any():
        raise UniverseError("két aktív instrumentum ugyanazzal a tickerrel")
    unknown = set(frame["asset_class"]) - ASSET_CLASSES
    if unknown:
        raise UniverseError(f"ismeretlen eszközosztály: {sorted(unknown)}")


def active_on(frame: pd.DataFrame, day: date) -> pd.DataFrame:
    """Az adott napon az univerzumhoz tartozó instrumentumok."""
    pairs = zip(frame["valid_from"], frame["valid_to"], strict=True)
    mask = [f <= day and (t is None or t >= day) for f, t in pairs]
    return frame[mask]
