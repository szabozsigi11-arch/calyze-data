"""Az értesítések napi piaci összefoglalója (spec/07, 6.).

Ez a futás csak a PIACI számokat küldi az adatbázisnak
(`enqueue_daily_notifications`). Hogy kinek megy ki és milyen nyelven, azt az
adatbázis dönti el; a nyilvános futás felhasználói adatot nem lát, és a
naplójába is csak darabszám kerül.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import requests

from pipeline import log as logging_setup
from pipeline.calendar import calendar

log = logging_setup.get_logger(__name__)

#: A naptár ablaka a mai naptól, naptári napban. Hátra: a legrégebbi még
#: nyitott 60 napos tézis kezdőnapja is beleférjen; előre: a célnapja is.
SESSIONS_BACK_DAYS = 150
SESSIONS_AHEAD_DAYS = 150


def _next_session(session: date) -> date | None:
    cal = calendar()
    ts = pd.Timestamp(session)
    if ts >= cal.last_session:
        return None
    return cal.next_session(ts).date()


def digest(latest: dict[str, object]) -> dict[str, object]:
    """A `latest.json`-ból az értesítésekhez szükséges piaci rész."""
    session = date.fromisoformat(str(latest["session"]))
    nxt = _next_session(session)
    resolved = latest.get("resolved") if isinstance(latest.get("resolved"), dict) else {}
    shock = latest.get("market_shock") if isinstance(latest.get("market_shock"), dict) else {}
    upcoming = latest.get("upcoming_events") if isinstance(latest.get("upcoming_events"), list) else []
    events_next = []
    if nxt is not None:
        for e in upcoming:
            if not isinstance(e, dict):
                continue
            day = date.fromisoformat(str(e["day"]))
            # a következő kereskedési napra eső esemény: „holnap”
            if session < day <= nxt:
                events_next.append({"kind": e["kind"], "day": e["day"], "time_et": e["time_et"]})
    return {
        "session": session.isoformat(),
        "resolved": {
            "count": int(resolved.get("count", 0) or 0),  # type: ignore[union-attr]
            "hits": int(resolved.get("hits", 0) or 0),  # type: ignore[union-attr]
            "baseline_hits": int(resolved.get("baseline_hits", 0) or 0),  # type: ignore[union-attr]
            "on": resolved.get("on"),  # type: ignore[union-attr]
        },
        "shock": {
            "signals": list(shock.get("signals", [])) if shock.get("status") == "ok" else [],  # type: ignore[union-attr]
            "withheld": bool(shock.get("withheld", False)),  # type: ignore[union-attr]
            "instruments_flagged": int(shock.get("instruments_flagged", 0) or 0),  # type: ignore[union-attr]
        },
        "events_next_session": events_next,
        # a hét utolsó kereskedési napja után megy ki a heti áttekintő
        "week_end": nxt is None or nxt.isocalendar()[1] != session.isocalendar()[1],
    }


def enqueue(url: str, secret_key: str, latest: dict[str, object]) -> int | None:
    """Az összefoglaló elküldése. Hiba esetén csak a státusz kerül a naplóba."""
    if not url or not secret_key:
        return None
    try:
        body = digest(latest)
        response = requests.post(
            f"{url.rstrip('/')}/rest/v1/rpc/enqueue_daily_notifications",
            headers={"apikey": secret_key, "Authorization": f"Bearer {secret_key}"},
            json={"p": body},
            timeout=30,
        )
    except Exception as error:  # noqa: BLE001 — az értesítés nem állíthatja meg a közzétételt
        log.warning("notify_failed", error=type(error).__name__)
        return None
    if response.status_code != 200:
        log.warning("notify_failed", status=response.status_code)
        return None
    count = int(response.json())
    log.info("notify_enqueued", notifications=count)
    return count


def session_rows(today: date) -> list[dict[str, str]]:
    """A NYSE kereskedési napjai a zárás időpontjával (rövidített napon 13:00).

    Nyilvános adat: az adatbázis ebből számolja ki, melyik tézis zárul ma
    (0021), ugyanazzal a szabállyal, mint a kiértékelés.
    """
    cal = calendar()
    start = pd.Timestamp(today - timedelta(days=SESSIONS_BACK_DAYS))
    end = min(pd.Timestamp(today + timedelta(days=SESSIONS_AHEAD_DAYS)), cal.last_session)
    return [
        {"session": s.date().isoformat(), "close_at": cal.session_close(s).isoformat()}
        for s in cal.sessions_in_range(start, end)
    ]


def push_sessions(url: str, secret_key: str, today: date) -> int | None:
    """A naptár feltöltése. Hiba esetén csak a státusz kerül a naplóba."""
    if not url or not secret_key:
        return None
    try:
        response = requests.post(
            f"{url.rstrip('/')}/rest/v1/rpc/set_trading_sessions",
            headers={"apikey": secret_key, "Authorization": f"Bearer {secret_key}"},
            json={"p": session_rows(today)},
            timeout=30,
        )
    except Exception as error:  # noqa: BLE001 — a naptár nem állíthatja meg a közzétételt
        log.warning("sessions_failed", error=type(error).__name__)
        return None
    # A 404: a 0021-es migráció még nincs fent. Nem hiba, csak még nincs hová.
    if response.status_code != 200:
        log.warning("sessions_failed", status=response.status_code)
        return None
    count = int(response.json())
    log.info("sessions_pushed", sessions=count)
    return count


def calendar_rows() -> list[dict[str, str]]:
    """A nem NYSE-naptárú papírok (ma: a kripto, `24/7`). Ami nincs benne, az NYSE."""
    from pipeline.universe import load_crypto_universe

    crypto = load_crypto_universe()
    return [{"instrument_id": i, "calendar": "24/7"} for i in crypto["instrument_id"]]


def push_calendars(url: str, secret_key: str) -> int | None:
    """A papír → naptár párok feltöltése (0022). Hiba esetén csak a státusz megy a naplóba."""
    if not url or not secret_key:
        return None
    try:
        response = requests.post(
            f"{url.rstrip('/')}/rest/v1/rpc/set_instrument_calendars",
            headers={"apikey": secret_key, "Authorization": f"Bearer {secret_key}"},
            json={"p": calendar_rows()},
            timeout=30,
        )
    except Exception as error:  # noqa: BLE001 — a naptár nem állíthatja meg a közzétételt
        log.warning("calendars_failed", error=type(error).__name__)
        return None
    # A 404: a 0022-es migráció még nincs fent.
    if response.status_code != 200:
        log.warning("calendars_failed", status=response.status_code)
        return None
    count = int(response.json())
    log.info("calendars_pushed", instruments=count)
    return count
