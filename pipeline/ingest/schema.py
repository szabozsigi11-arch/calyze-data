"""A napi árfolyam kanonikus sémája.

Minden forrás erre fordít. A későbbi rétegek nem tudják, honnan jött az adat,
csak azt, amit a `source` oszlop mond. A `close` a forrás záróára (a
felosztásokra jellemzően visszamenőleg igazítva), az `adj_close` felosztásra
és osztalékra is igazított — a hozam ebből számol (teljes hozam, spec/05, 2.5).
"""

from __future__ import annotations

from typing import Final

import pandas as pd

PRICE_COLUMNS: Final = (
    "instrument_id",
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "source",
    "fetched_at",
    "quality",
)

#: A forrás-adapterek kimenete: még tickerrel, azonosító nélkül.
PROVIDER_COLUMNS: Final = ("ticker", "date", "open", "high", "low", "close", "adj_close", "volume")

#: Vállalati események a letöltött ablakban (spec/05, 2.5).
ACTION_COLUMNS: Final = ("ticker", "date", "dividend", "split_ratio")


class SchemaError(ValueError):
    """Egy forrás a várt sémától eltérő táblát adott."""


def conform_provider_frame(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    """Egy adapter kimenetét a közös alakra hozza, és rögtön ellenőrzi.

    A duplikált oszlopnevet itt fogjuk meg, ahol még tudni, melyik forrás
    okozta: a Kalibrában a Tiingo `adjOpen` → `open` átnevezése épp így
    rontotta el csendben az összefűzést.
    """
    duplicates = frame.columns[frame.columns.duplicated()].unique().tolist()
    if duplicates:
        raise SchemaError(f"{source}: duplikált oszlopnevek {sorted(duplicates)}")
    missing = set(PROVIDER_COLUMNS) - set(frame.columns)
    if missing:
        raise SchemaError(f"{source}: hiányzó oszlopok {sorted(missing)}")

    out = frame.loc[:, list(PROVIDER_COLUMNS)].copy()
    out["ticker"] = out["ticker"].astype("string")
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None).dt.normalize().dt.date
    for col in ("open", "high", "low", "close", "adj_close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
    out = out.dropna(subset=["close"])
    out["source"] = source
    return out


def empty_actions() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in ACTION_COLUMNS})
