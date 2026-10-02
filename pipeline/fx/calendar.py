"""A TARGET-naptár: azok a napok, amelyeken az EKB referencia-árfolyamot közöl.

Hétfőtől péntekig, kivéve újév, nagypéntek, húsvéthétfő, május 1., december
25. és 26. (`docs/fx-univerzum.md`, 4.). Saját, néhány soros szabály: a
naptár-könyvtárban nincs TARGET-naptár, és ennyi ünnepnapért nem érdemes
függőséget felvenni. A húsvét a `dateutil` számításából jön.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo

from dateutil.easter import easter

#: A fixálás időpontja (a jegybankok napi egyeztetése).
FIXING = time(14, 10)
CET = ZoneInfo("Europe/Berlin")


@cache
def holidays(year: int) -> frozenset[date]:
    e = easter(year)
    return frozenset(
        {
            date(year, 1, 1),
            e - timedelta(days=2),  # nagypéntek
            e + timedelta(days=1),  # húsvéthétfő
            date(year, 5, 1),
            date(year, 12, 25),
            date(year, 12, 26),
        }
    )


def is_target_day(day: date) -> bool:
    return day.weekday() < 5 and day not in holidays(day.year)


def target_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if is_target_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def offset(day: date, n: int) -> date:
    """Az `n`-edik TARGET-nap `day` után (a horizont vége)."""
    d, left = day, n
    while left > 0:
        d += timedelta(days=1)
        if is_target_day(d):
            left -= 1
    return d


def fixing_at(day: date) -> datetime:
    """A nap fixálásának pillanata UTC-ben (télen 13:10, nyáron 12:10)."""
    return datetime.combine(day, FIXING, tzinfo=CET).astimezone(UTC)


def last_fixing_day(now: datetime) -> date:
    """Az utolsó TARGET-nap, amelynek a fixálása `now` előtt volt."""
    d = now.astimezone(UTC).date()
    while not (is_target_day(d) and fixing_at(d) <= now.astimezone(UTC)):
        d -= timedelta(days=1)
    return d


def first_fixing_day(ts: datetime) -> date:
    """Az első TARGET-nap, amelynek fixálása `ts` után vagy vele egyidőben van.

    A tézis kezdőnapja (`tezis-kiertekeles.md`, 11.): a NYSE-zárás helyett a
    fixálás számít.
    """
    d = ts.astimezone(UTC).date() - timedelta(days=1)
    while not (is_target_day(d) and fixing_at(d) >= ts.astimezone(UTC)):
        d += timedelta(days=1)
    return d
