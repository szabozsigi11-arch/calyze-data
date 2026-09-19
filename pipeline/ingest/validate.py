"""Adatminőség-ellenőrzés.

A gyanús sort nem töröljük, hanem megjelöljük (`quality = "suspect"`): a
törlés lyukat hagyna az idősorban, és a Kalibra tapasztalata szerint a
kiugró sorok többsége valódi piaci esemény volt, nem adathiba. A döntés a
feature-rétegé, ahol már látszik a környezet.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from pipeline.calendar import sessions


class ValidationError(ValueError):
    """A letöltött adat nem mehet tovább (pl. jövőbeli dátum, ismétlődő sor)."""


def mark_quality(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    body_low = out[["open", "close"]].min(axis=1)
    body_high = out[["open", "close"]].max(axis=1)
    suspect = (
        (out["close"] <= 0)
        | (out["low"] > body_low + 1e-9)
        | (out["high"] < body_high - 1e-9)
        | (out["low"] > out["high"])
        | (out["volume"] < 0)
    )
    out["quality"] = suspect.map({True: "suspect", False: "ok"}).astype("string")
    return out


def check_hard_rules(frame: pd.DataFrame, last_session: date) -> None:
    """Olyan hibák, amelyekkel a futás nem folytatódhat."""
    if frame.duplicated(subset=["instrument_id", "date"]).any():
        raise ValidationError("ismétlődő (instrument_id, date) sor")
    if (frame["date"] > last_session).any():
        # Jövőbeli dátum: a forrás a még le nem zárt napot is visszaadta —
        # ha ez bekerülne, a zárás előtti ár zárásként élne tovább.
        raise ValidationError("a lezárt utolsó kereskedési napnál későbbi dátum")


def drop_off_session(frame: pd.DataFrame, calendar_code: str = "XNYS") -> tuple[pd.DataFrame, int]:
    """A nem kereskedési napra eső sorokat eldobja, és megszámolja.

    A forrás néha zárvatartási napra is ad sort (pl. gyásznap); a naptár a
    mérvadó, nem a forrás. Nem állítja meg a futást, de a jelentésben látszik.
    """
    if frame.empty:
        return frame, 0
    valid = set(sessions(min(frame["date"]), max(frame["date"]), calendar_code))
    on = frame["date"].isin(valid)
    return frame[on], int((~on).sum())


def drop_unclosed(frame: pd.DataFrame, last_session: date) -> pd.DataFrame:
    """A még le nem zárt nap sorait eldobja (a yfinance napközben részleges napot ad)."""
    return frame[frame["date"] <= last_session]
