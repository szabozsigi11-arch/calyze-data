"""Tőzsdei naptár (spec/05, 5b).

A kereskedési napokat, ünnepeket és rövidített napokat az `exchange_calendars`
adja (NYSE = XNYS); saját ünnepnaplista nincs. A kereskedési nap `date` a
tőzsde idejében, az időpont `timestamptz` UTC-ben — soha nem fix eltolás.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import cache

import exchange_calendars as xcals
import pandas as pd

#: A naptár kezdete. Az `exchange_calendars` alapból csak 20 évre visszamenőleg
#: ad napokat — enélkül a 2006 szeptembere előtti sorok „zárvatartási napként”
#: kiesnének (ez az első próbafuttatáson meg is történt).
CALENDAR_START = "2000-01-03"


@cache
def calendar(code: str = "XNYS") -> xcals.ExchangeCalendar:
    return xcals.get_calendar(code, start=CALENDAR_START)


def is_session(day: date, code: str = "XNYS") -> bool:
    return bool(calendar(code).is_session(pd.Timestamp(day)))


def sessions(start: date, end: date, code: str = "XNYS") -> list[date]:
    cal = calendar(code)
    first = max(pd.Timestamp(start), cal.first_session)
    last = min(pd.Timestamp(end), cal.last_session)
    if first > last:
        return []
    return [ts.date() for ts in cal.sessions_in_range(first, last)]


def last_closed_session(now: datetime, code: str = "XNYS") -> date:
    """Az utolsó olyan kereskedési nap, amelynek a zárása `now` előtt volt.

    Rövidített napon (pl. hálaadás utáni péntek) a zárás korábban van; ezt a
    naptár tudja, nem mi számoljuk.
    """
    if now.tzinfo is None:
        raise ValueError("A `now` időzóna nélkül nem értelmezhető — UTC kell.")
    cal = calendar(code)
    ts = pd.Timestamp(now.astimezone(UTC))
    # Az UTC-dátumból indulunk: New Yorkban ilyenkor legfeljebb ugyanaz a nap
    # vagy az előző van, és a zárás UTC-időpontja dönt, nem a naptári nap.
    session = cal.date_to_session(pd.Timestamp(ts.date()), direction="previous")
    if cal.session_close(session) > ts:
        session = cal.previous_session(session)
    return session.date()


def sessions_back(end: date, count: int, code: str = "XNYS") -> list[date]:
    """Az `end` napig (bezárólag) visszafelé `count` kereskedési nap, időrendben."""
    cal = calendar(code)
    end_ts = pd.Timestamp(end)
    if not cal.is_session(end_ts):
        end_ts = cal.date_to_session(end_ts, direction="previous")
    return [ts.date() for ts in cal.sessions_window(end_ts, -count)]


def session_lag(available: date, expected: date, code: str = "XNYS") -> int:
    """Hány kereskedési nappal marad el az adat az elvárt naptól.

    Nulla, ha ugyanaz a nap. A forrás akkor is „elmarad", ha egyetlen napot
    hagy ki — de egy nap kihagyás nem indok a leállásra, több már igen.
    """
    if available >= expected:
        return 0
    return max(len(sessions(available, expected, code)) - 1, 0)
