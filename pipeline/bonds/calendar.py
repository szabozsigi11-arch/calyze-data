"""A kötvénynap-naptár (`docs/kotveny.md`, 2.): munkanap, kivéve a szövetségi
ünnepeket és nagypénteket. A „zárás” a 15:30-as (New York-i idő) felvétel,
a közzététel 18:00-ig történik.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo

from dateutil.easter import easter
from pandas.tseries.holiday import USFederalHolidayCalendar

ET = ZoneInfo("America/New_York")
SNAPSHOT = time(15, 30)
PUBLISHED = time(18, 0)


@cache
def holidays(year: int) -> frozenset[date]:
    fed = {d.date() for d in USFederalHolidayCalendar().holidays(f"{year}-01-01", f"{year}-12-31")}
    return frozenset(fed | {easter(year) - timedelta(days=2)})


def is_bond_day(day: date) -> bool:
    return day.weekday() < 5 and day not in holidays(day.year)


def bond_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if is_bond_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def offset(day: date, n: int) -> date:
    d, left = day, n
    while left > 0:
        d += timedelta(days=1)
        if is_bond_day(d):
            left -= 1
    return d


def snapshot_at(day: date) -> datetime:
    """A nap felvételének pillanata UTC-ben (15:30 ET)."""
    return datetime.combine(day, SNAPSHOT, tzinfo=ET).astimezone(UTC)


def last_bond_day(now: datetime) -> date:
    """Az utolsó kötvénynap, amelynek görbéje `now`-ra már közzé van téve (18:00 ET)."""
    d = now.astimezone(UTC).date()
    while not (is_bond_day(d) and datetime.combine(d, PUBLISHED, tzinfo=ET) <= now.astimezone(UTC)):
        d -= timedelta(days=1)
    return d
