"""A felhasználói tézisek kiértékelése (docs/tezis-kiertekeles.md).

A tézis az ember előre rögzített állítása; itt ugyanazzal a szabállyal
pontozzuk, mint a modellt (`pipeline.model.evaluate`), ugyanazon az
ablakon, a modell és a naiv baseline aznapi becslése mellett.

**Adatvédelem.** Ez a repó és az Actions-naplója nyilvános. A tézisek csak
a futás memóriájában léteznek: a napló kizárólag darabszámot ír, azonosítót,
papírt, indoklást vagy valószínűséget soha (spec/05, 1. fejezet). A kimenetel
a Supabase-be megy vissza, a service_role kulccsal; a tézis tartalmához az
adatbázis-trigger miatt ez sem nyúlhat, és egy kiértékelést csak egyszer írhat.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

import pandas as pd
import requests

from pipeline import log as logging_setup
from pipeline.calendar import calendar

log = logging_setup.get_logger(__name__)

#: A kiértékeléshez szükséges oszlopok; a szöveges mezőket le sem kérjük.
SELECT = "id,instrument_id,direction,probability,horizon,created_at"


@dataclass(frozen=True)
class Thesis:
    id: str
    instrument_id: str
    direction: str
    probability: float
    horizon: int
    created_at: datetime


class JournalStore(Protocol):
    def open_theses(self) -> list[Thesis]: ...

    def write_outcome(self, thesis_id: str, outcome: dict[str, object]) -> bool: ...


def start_session(created_at: datetime, code: str = "XNYS") -> date:
    """Az első kereskedési nap, amelynek zárása a rögzítéskor vagy utána van.

    Napközben rögzített tézis aznap zárásától indul, zárás után rögzített a
    következő napétól: a rögzítéskor már ismert napközbeni mozgás nem számít.
    """
    if created_at.tzinfo is None:
        raise ValueError("A rögzítési idő időzóna nélkül nem értelmezhető — UTC kell.")
    if code == "TARGET":
        # Deviza: a zárás az EKB-fixálás (tezis-kiertekeles.md, 11.).
        from pipeline.fx.calendar import first_fixing_day

        return first_fixing_day(created_at)
    cal = calendar(code)
    ts = pd.Timestamp(created_at.astimezone(UTC))
    session = cal.date_to_session(pd.Timestamp(ts.date()), direction="next")
    while cal.session_close(session) < ts:
        session = cal.next_session(session)
    return session.date()


def target_session(start: date, horizon: int, code: str = "XNYS") -> date:
    if code == "TARGET":
        from pipeline.fx.calendar import offset

        return offset(start, horizon)
    return calendar(code).session_offset(pd.Timestamp(start), horizon).date()


def _brier(prob_up: float, up: bool) -> float:
    return (prob_up - float(up)) ** 2


def _hit(prob_up: float, up: bool) -> bool:
    return (prob_up > 0.5) == up


def resolve_theses(
    theses: Iterable[Thesis],
    series: dict[str, pd.Series],
    forecasts: pd.DataFrame,
    last_session: date,
    calendar_code: str = "XNYS",
) -> tuple[dict[str, dict[str, object]], dict[str, int]]:
    """Kiértékeli a lejárt téziseket.

    A `calendar_code` a papírok naptára: a kripto-futás `24/7`-tel hívja, a
    saját árfolyamaival (`docs/tezis-kiertekeles.md`, 10.). Amelyik tézis
    papírjára nincs ár ebben a futásban, az kimarad, és a másik futás zárja le.

    Visszaad: azonosító → a kiírandó mezők, és a darabszámok a naplóhoz.
    """
    lookup: dict[tuple[str, date, int], tuple[float, float]] = {}
    if not forecasts.empty:
        for f in forecasts.itertuples():
            key = (str(f.instrument_id), f.session, int(f.horizon))
            lookup[key] = (float(f.prob_up), float(f.baseline_prob))

    out: dict[str, dict[str, object]] = {}
    counts = {"open": 0, "not_due": 0, "no_price": 0, "resolved": 0, "no_model": 0}
    for t in theses:
        counts["open"] += 1
        start = start_session(t.created_at, calendar_code)
        end_day = target_session(start, t.horizon, calendar_code)
        if end_day > last_session:
            counts["not_due"] += 1
            continue
        history = series.get(t.instrument_id)
        if history is None or start not in history.index:
            counts["no_price"] += 1
            continue
        start_price = float(history.loc[start])
        if end_day in history.index:
            end_price, kind = float(history.loc[end_day]), "normal"
        else:
            # Kivezetés vagy felfüggesztés: az utolsó ismert zárás zár, mint a
            # modell becslésénél (docs/tezis-kiertekeles.md, 2.).
            earlier = history[history.index <= end_day]
            if earlier.empty or earlier.index[-1] <= start:
                counts["no_price"] += 1
                continue
            end_price, kind = float(earlier.iloc[-1]), "delisted_or_halted"

        simple = end_price / start_price - 1
        up = simple > 0
        p_up = t.probability if t.direction == "long" else 1 - t.probability
        row: dict[str, object] = {
            "start_session": start.isoformat(),
            "target_session": end_day.isoformat(),
            "outcome_return": round(simple, 8),
            "outcome_hit": _hit(p_up, up),
            "outcome_brier": round(_brier(p_up, up), 8),
            "resolution_type": kind,
            "resolved_at": datetime.now(UTC).isoformat(),
        }
        model = lookup.get((t.instrument_id, start, t.horizon))
        if model is None:
            counts["no_model"] += 1
        else:
            model_up, base_up = model
            toward = (lambda p: p) if t.direction == "long" else (lambda p: 1 - p)
            row |= {
                "model_prob": round(toward(model_up), 8),
                "baseline_prob": round(toward(base_up), 8),
                "model_hit": _hit(model_up, up),
                "baseline_hit": _hit(base_up, up),
                "model_brier": round(_brier(model_up, up), 8),
                "baseline_brier": round(_brier(base_up, up), 8),
            }
        out[t.id] = row
        counts["resolved"] += 1
    return out, counts


class SupabaseJournal:
    """A napló táblája a PostgREST-en át, service_role kulccsal."""

    RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

    def __init__(self, url: str, secret_key: str, timeout: float = 30) -> None:
        self.base = f"{url.rstrip('/')}/rest/v1/journal_entries"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": secret_key,
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/json",
            }
        )
        self.timeout = timeout

    def _request(self, method: str, **kwargs: object) -> requests.Response:
        for attempt in range(3):
            response = self.session.request(method, self.base, timeout=self.timeout, **kwargs)  # type: ignore[arg-type]
            if response.status_code not in self.RETRY_STATUS or attempt == 2:
                return response
            time.sleep(2**attempt)
        raise AssertionError("elérhetetlen")  # pragma: no cover

    def open_theses(self) -> list[Thesis]:
        response = self._request(
            "GET",
            params={
                "select": SELECT,
                "mode": "eq.thesis",
                "registered": "is.true",
                "resolved_at": "is.null",
                "status": "neq.deleted",
                "limit": "50000",
            },
        )
        # A hibaüzenet a státuszkóddal megy tovább, a válasz törzse nem: abban
        # felhasználói adat is lehetne.
        if response.status_code != 200:
            raise RuntimeError(f"journal_fetch_failed:{response.status_code}")
        return [
            Thesis(
                id=str(r["id"]),
                instrument_id=str(r["instrument_id"]),
                direction=str(r["direction"]),
                probability=float(r["probability"]),
                horizon=int(r["horizon"]),
                created_at=datetime.fromisoformat(str(r["created_at"])),
            )
            for r in response.json()
        ]

    def write_outcome(self, thesis_id: str, outcome: dict[str, object]) -> bool:
        # A `resolved_at=is.null` feltétel miatt a kétszeri futás sem ír kétszer.
        response = self._request(
            "PATCH",
            params={"id": f"eq.{thesis_id}", "resolved_at": "is.null"},
            json=outcome,
            headers={"Prefer": "return=minimal"},
        )
        return response.status_code in (200, 204)


def run(
    store: JournalStore,
    series: dict[str, pd.Series],
    forecasts: pd.DataFrame,
    last_session: date,
    calendar_code: str = "XNYS",
) -> dict[str, int]:
    theses = [t for t in store.open_theses() if t.instrument_id in series]
    outcomes, counts = resolve_theses(theses, series, forecasts, last_session, calendar_code)
    written = sum(1 for thesis_id, row in outcomes.items() if store.write_outcome(thesis_id, row))
    counts["written"] = written
    counts["write_failed"] = len(outcomes) - written
    # Csak darabszám: ez a napló nyilvános.
    log.info("journal_resolve_done", **counts)
    return counts


def as_series(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """A teljes hozamú árfolyamok papíronként, dátum szerint rendezve."""
    return {
        str(instrument): g.set_index("date")["tr"].sort_index()
        for instrument, g in frame.groupby("instrument_id", sort=False)
    }


__all__ = [
    "SupabaseJournal",
    "Thesis",
    "as_series",
    "resolve_theses",
    "run",
    "start_session",
    "target_session",
]
