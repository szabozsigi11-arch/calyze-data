"""Ütemezett, hivatalos események a becslés ablakában (docs/naptar.md).

A lista kézzel karbantartott, a kiadók saját oldaláról. Egy sor soha nem
változik utólag: ha egy dátum módosul, új azonosítóval jön, a régi marad —
így a korábbi becslések jelölése visszakereshető.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from pipeline.calendar import calendar


@dataclass(frozen=True)
class Event:
    id: str
    kind: str
    day: date
    #: New York-i idő, tájékoztatásul
    time_et: str
    title: str


def _fomc(days: list[str]) -> list[Event]:
    return [Event(f"fomc-{d}", "fomc", date.fromisoformat(d), "14:00", "FOMC rate decision") for d in days]


def _bls(kind: str, title: str, days: list[str]) -> list[Event]:
    return [Event(f"{kind}-{d}", kind, date.fromisoformat(d), "08:30", title) for d in days]


def _ecb(days: list[str]) -> list[Event]:
    return [Event(f"ecb-{d}", "ecb", date.fromisoformat(d), "08:15", "ECB rate decision") for d in days]


#: federalreserve.gov/monetarypolicy/fomccalendars.htm (2026-09-27): az ülés 2. napja
FOMC = _fomc(
    [
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
        "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
        "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
    ]
)  # fmt: skip

#: bls.gov/schedule/news_release/cpi.htm (2026-09-27)
CPI = _bls(
    "cpi",
    "US consumer prices (CPI)",
    [
        "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10",
        "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10",
    ],
)  # fmt: skip

#: bls.gov/schedule/news_release/empsit.htm (2026-09-27)
NFP = _bls(
    "nfp",
    "US employment report (NFP)",
    [
        "2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08", "2026-06-05",
        "2026-07-02", "2026-08-07", "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
    ],
)  # fmt: skip

#: ecb.europa.eu/press/calendars/mgcgc (2026-09-27): a hátralévő 2026-os és a 2027-es döntések
ECB = _ecb(
    [
        "2026-10-29", "2026-12-17",
        "2027-02-04", "2027-03-18", "2027-04-29", "2027-06-10",
        "2027-07-22", "2027-09-09", "2027-10-28", "2027-12-16",
    ]
)  # fmt: skip

EVENTS: tuple[Event, ...] = tuple(sorted([*FOMC, *CPI, *NFP, *ECB], key=lambda e: (e.day, e.id)))

#: Meddig teljes a naptár: ezen túl a felület nem állítja, hogy nincs esemény.
COVERED_UNTIL = {
    "fomc": date(2027, 12, 31),
    "ecb": date(2027, 12, 31),
    "cpi": date(2026, 12, 31),
    "nfp": date(2026, 12, 31),
}


def _session_on_or_after(day: date) -> date:
    cal = calendar()
    # A naptár csak kb. egy évre előre ismeri a tőzsdenapokat; azon túli
    # esemény úgysem eshet egy legfeljebb 60 napos ablakba.
    if pd.Timestamp(day) > cal.last_session:
        return day
    return cal.date_to_session(pd.Timestamp(day), direction="next").date()


def events_in_window(start: date, end: date) -> list[Event]:
    """Az `S < D' ≤ E` ablakba eső események (docs/naptar.md, 2.)."""
    return [e for e in EVENTS if start < _session_on_or_after(e.day) <= end]


def calendar_flag(start: date, end: date | None) -> str:
    """A becslés-csomag oszlopa: az események azonosítói vesszővel, vagy üres."""
    if end is None:
        return ""
    return ",".join(e.id for e in events_in_window(start, end))


def uncovered_kinds(end: date) -> list[str]:
    """Az eseményfajták, amelyekről `end`-ig még nincs teljes naptárunk."""
    return sorted(kind for kind, until in COVERED_UNTIL.items() if end > until)


def attach_calendar(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["calendar_flag"] = [
        calendar_flag(s, t if t is not None and not pd.isna(t) else None)
        for s, t in zip(out["session"], out["target_session"], strict=True)
    ]
    return out


def upcoming(after: date, days: int = 45) -> list[Event]:
    """A következő napok eseményei a felületnek."""
    last = pd.Timestamp(after) + pd.Timedelta(days=days)
    return [e for e in EVENTS if after < e.day <= last.date()]
