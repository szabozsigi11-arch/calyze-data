"""A spec/05 5b kötelező időzóna-tesztjei."""

from datetime import date, datetime

import pytest

from pipeline.calendar import is_session, last_closed_session, sessions, sessions_back


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s + "+00:00")


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # Nyári időszámítás (EDT): a zárás 20:00 UTC.
        ("2026-09-18T19:59:00", date(2026, 9, 17)),
        ("2026-09-18T20:01:00", date(2026, 9, 18)),
        # Téli időszámítás (EST): a zárás 21:00 UTC — 20:30-kor még nyitva.
        ("2026-01-15T20:30:00", date(2026, 1, 14)),
        ("2026-01-15T21:01:00", date(2026, 1, 15)),
        # A két váltás közti hetek: az USA márc. 8-án már nyári időben van,
        # az EU csak márc. 29-én — Budapest és New York között 5 óra.
        ("2026-03-16T19:30:00", date(2026, 3, 13)),
        ("2026-03-16T20:05:00", date(2026, 3, 16)),
        # Ősszel fordítva: az EU okt. 25-én vált, az USA nov. 1-jén.
        ("2026-10-27T20:05:00", date(2026, 10, 27)),
        # Rövidített nap: hálaadás utáni péntek, zárás 13:00 ET = 18:00 UTC.
        ("2026-11-27T17:59:00", date(2026, 11, 25)),
        ("2026-11-27T18:01:00", date(2026, 11, 27)),
        # Hétvége és hétfő hajnal: a pénteki session a legutóbbi.
        ("2026-09-20T12:00:00", date(2026, 9, 18)),
        ("2026-09-21T00:30:00", date(2026, 9, 18)),
    ],
)
def test_last_closed_session(now, expected):
    assert last_closed_session(utc(now)) == expected


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError, match="UTC"):
        last_closed_session(datetime(2026, 9, 18, 21, 0))  # noqa: DTZ001 — szándékosan időzóna nélkül


def test_holidays_are_not_sessions():
    assert not is_session(date(2026, 11, 26))  # hálaadás
    assert not is_session(date(2026, 4, 3))  # nagypéntek
    assert not is_session(date(2026, 7, 3))  # a július 4-i ünnep szombatra esik, péntek zárva


def test_horizon_counts_sessions_not_calendar_days():
    # Ünnep a horizont közepén: a hálaadás (nov. 26.) kimarad, a rövidített
    # péntek (nov. 27.) viszont teljes értékű session.
    assert sessions_back(date(2026, 11, 30), 5) == [
        date(2026, 11, 23),
        date(2026, 11, 24),
        date(2026, 11, 25),
        date(2026, 11, 27),
        date(2026, 11, 30),
    ]


def test_history_reaches_back_before_2006():
    # Az exchange_calendars alapból csak 20 évre visszamenőleg ad napot.
    assert sessions(date(2005, 1, 3), date(2005, 1, 7)) == [date(2005, 1, d) for d in (3, 4, 5, 6, 7)]
