"""A rögzített forgatókönyvek napi feldolgozása (`docs/forgatokonyv.md`, 5.).

Két lépés, mindkettő egyszer írhat (a 0032-es trigger őrzi):

1. **Pin:** a rögzítés előtti utolsó lenyomatolt becslésből és az akkor
   érvényes kalibrációból (`<osztály>/scenario.json`) kiszámolja a feltételes
   esélyt és sávot, és ráírja. A kliens számot nem küld, így utólag nem
   választható „jobb” szám.
2. **Lezárás:** ha a célnap elmúlt, a lenyomatolt napi csomagok sokk-jeleiből
   eldönti, teljesült-e a feltétel. Ha igen, a naiv baseline ellen pontoz; ha
   nem (vagy egy napra nincs ellenőrizhető jel), `condition_failed`: nem
   pontozzuk, de darabszámként látszik.

**Adatvédelem.** Mint a téziseknél: a napló csak darabszámot ír.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

import numpy as np
import pandas as pd
import requests

from pipeline import log as logging_setup
from pipeline.ingest.storage import Storage

log = logging_setup.get_logger(__name__)

SELECT = (
    "id,instrument_id,horizon,assumed_regime,created_at,pinned_at,"
    "prob_up,baseline_prob,forecast_session,target_session"
)
DISPLAY_BUCKET = "display"


@dataclass(frozen=True)
class Entry:
    id: str
    instrument_id: str
    horizon: int
    assumed_regime: str
    created_at: datetime
    pinned: bool
    prob_up: float | None
    baseline_prob: float | None
    forecast_session: date | None
    target_session: date | None


class ScenarioStore(Protocol):
    def open_entries(self) -> list[Entry]: ...

    def write(self, entry_id: str, fields: dict[str, object], *, pin: bool) -> bool: ...


def _cell(calibration: dict[str, object], horizon: int, regime: str) -> dict[str, object] | None:
    horizons = calibration.get("horizons", {})
    cell = horizons.get(str(horizon), {}).get(regime) if isinstance(horizons, dict) else None
    return cell if isinstance(cell, dict) and "quantiles" in cell else None


def conditional(
    point: float, scale: float, cell: dict[str, object], levels: list[float]
) -> tuple[float, float, float]:
    """Ugyanaz, mint a felületen (`lib/scenario.ts`): esély és sáv a hírmentes hibákból."""
    quantiles = np.asarray(cell["quantiles"], dtype="float64")
    x = -point / scale
    prob = 1.0 - float(np.interp(x, quantiles, np.asarray(levels, dtype="float64"), left=0.0, right=1.0))
    q = float(cell["band_q"])  # type: ignore[arg-type]
    return prob, point - q * scale, point + q * scale


def pin_entries(
    entries: Iterable[Entry], forecasts: pd.DataFrame, calibration: dict[str, object] | None
) -> dict[str, dict[str, object]]:
    """A még számtalan bejegyzések száma a rögzítés előtti utolsó lenyomatból."""
    out: dict[str, dict[str, object]] = {}
    if forecasts.empty:
        return out
    made = pd.to_datetime(forecasts["made_at"], utc=True)
    levels = list(calibration.get("quantile_levels", [])) if calibration else []
    for e in entries:
        if e.pinned:
            continue
        before = forecasts[made <= pd.Timestamp(e.created_at)]
        if before.empty:
            continue  # a rögzítés előtt még nem volt csomag: a következő futás próbálja
        session = max(before["session"])
        row = before[
            (before["session"] == session)
            & (before["instrument_id"] == e.instrument_id)
            & (before["horizon"] == e.horizon)
        ]
        now = datetime.now(UTC).isoformat()
        if row.empty:
            out[e.id] = {"status": "no_estimate", "resolved_at": now, "pinned_at": now}
            continue
        r = row.iloc[0]
        scale = r.get("scale")
        withheld = bool(r.get("withheld")) if pd.notna(r.get("withheld")) else False
        regime = (
            str(r.get("regime"))
            if e.assumed_regime == "today" and pd.notna(r.get("regime"))
            else e.assumed_regime
        )
        regime = regime if regime in ("calm", "normal", "stressed") else "all"
        cell = _cell(calibration, e.horizon, regime) if calibration else None
        if withheld or scale is None or pd.isna(scale) or cell is None or not levels:
            out[e.id] = {"status": "no_estimate", "resolved_at": now, "pinned_at": now}
            continue
        prob, low, high = conditional(float(r["expected_return"]), float(scale), cell, levels)
        out[e.id] = {
            "forecast_session": pd.Timestamp(session).date().isoformat(),
            "regime_used": regime,
            "prob_up": round(prob, 6),
            "band_low": round(low, 6),
            "band_high": round(high, 6),
            "baseline_prob": round(float(r["baseline_prob"]), 6),
            "target_session": str(pd.Timestamp(r["target_session"]).date()),
            "pinned_at": now,
        }
    return out


def condition_held(forecasts: pd.DataFrame, instrument_id: str, start: date, target: date) -> bool:
    """Igaz, ha az ablak minden napjára van lenyomatolt, rendben lévő jel, és egyik sem szólt."""
    sessions = sorted({d for d in forecasts["session"] if start < d <= target})
    if not sessions or "shock_signals" not in forecasts or "shock_market" not in forecasts:
        return False
    for day in sessions:
        part = forecasts[(forecasts["session"] == day) & (forecasts["instrument_id"] == instrument_id)]
        if part.empty:
            return False
        r = part.iloc[0]
        if "shock_status" in part and str(r.get("shock_status")) != "ok":
            return False
        if str(r.get("shock_signals") or "") or str(r.get("shock_market") or ""):
            return False
    return True


def resolve_entries(
    entries: Iterable[Entry], series: dict[str, pd.Series], forecasts: pd.DataFrame, last_session: date
) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for e in entries:
        if not e.pinned or e.forecast_session is None or e.target_session is None or e.prob_up is None:
            continue
        if e.target_session > last_session:
            continue
        history = series.get(e.instrument_id)
        if history is None or e.forecast_session not in history.index:
            continue
        earlier = history[history.index <= e.target_session]
        if earlier.empty or earlier.index[-1] <= e.forecast_session:
            continue
        now = datetime.now(UTC).isoformat()
        if not condition_held(forecasts, e.instrument_id, e.forecast_session, e.target_session):
            out[e.id] = {"status": "condition_failed", "resolved_at": now}
            continue
        simple = float(earlier.iloc[-1]) / float(history.loc[e.forecast_session]) - 1
        up = simple > 0
        out[e.id] = {
            "status": "resolved",
            "outcome_return": round(simple, 8),
            "hit": (e.prob_up > 0.5) == up,
            "baseline_hit": ((e.baseline_prob or 0.5) > 0.5) == up,
            "resolved_at": now,
        }
    return out


class SupabaseScenarios:
    """A forgatókönyv-tábla a PostgREST-en át, service_role kulccsal."""

    RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

    def __init__(self, url: str, secret_key: str, timeout: float = 30) -> None:
        self.base = f"{url.rstrip('/')}/rest/v1/scenario_entries"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": secret_key,
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/json",
            }
        )
        self.timeout = timeout

    @classmethod
    def beside(cls, journal: object) -> SupabaseScenarios | None:
        """Ugyanazzal a kapcsolattal, mint a tézisek tárja; helyi futásban és tesztben nincs."""
        from pipeline.journal.resolve import SupabaseJournal

        if not isinstance(journal, SupabaseJournal):
            return None
        store = cls.__new__(cls)
        store.base = journal.base.replace("/journal_entries", "/scenario_entries")
        store.session = journal.session
        store.timeout = journal.timeout
        return store

    def _request(self, method: str, **kwargs: object) -> requests.Response:
        for attempt in range(3):
            response = self.session.request(method, self.base, timeout=self.timeout, **kwargs)  # type: ignore[arg-type]
            if response.status_code not in self.RETRY_STATUS or attempt == 2:
                return response
            time.sleep(2**attempt)
        raise AssertionError("elérhetetlen")  # pragma: no cover

    def open_entries(self) -> list[Entry]:
        response = self._request("GET", params={"select": SELECT, "status": "eq.open", "limit": "50000"})
        # A 404: a 0032-es migráció még nincs fent. Nem hiba, csak még nincs mit feldolgozni.
        if response.status_code == 404:
            return []
        if response.status_code != 200:
            raise RuntimeError(f"scenario_fetch_failed:{response.status_code}")

        def day(v: object) -> date | None:
            return date.fromisoformat(str(v)) if v else None

        return [
            Entry(
                id=str(r["id"]),
                instrument_id=str(r["instrument_id"]),
                horizon=int(r["horizon"]),
                assumed_regime=str(r["assumed_regime"]),
                created_at=datetime.fromisoformat(str(r["created_at"])),
                pinned=r.get("pinned_at") is not None,
                prob_up=None if r.get("prob_up") is None else float(r["prob_up"]),
                baseline_prob=None if r.get("baseline_prob") is None else float(r["baseline_prob"]),
                forecast_session=day(r.get("forecast_session")),
                target_session=day(r.get("target_session")),
            )
            for r in response.json()
        ]

    def write(self, entry_id: str, fields: dict[str, object], *, pin: bool) -> bool:
        # A feltétel miatt a kétszeri futás sem ír kétszer.
        guard = {"pinned_at": "is.null"} if pin else {"resolved_at": "is.null"}
        response = self._request(
            "PATCH",
            params={"id": f"eq.{entry_id}", **guard},
            json=fields,
            headers={"Prefer": "return=minimal"},
        )
        return response.status_code in (200, 204)


def load_calibration(storage: Storage, display_prefix: str) -> dict[str, object] | None:
    blob = storage.download(DISPLAY_BUCKET, f"{display_prefix}scenario.json")
    return None if blob is None else json.loads(blob)


def run(
    store: ScenarioStore,
    storage: Storage,
    series: dict[str, pd.Series],
    forecasts: pd.DataFrame,
    last_session: date,
    display_prefix: str,
) -> dict[str, int]:
    """Egy eszközosztály forgatókönyvei: csak azok, amelyek papírjára van ár ebben a futásban."""
    entries = [e for e in store.open_entries() if e.instrument_id in series]
    pins = pin_entries(entries, forecasts, load_calibration(storage, display_prefix))
    pinned = sum(1 for i, f in pins.items() if store.write(i, f, pin=True))
    # A most rögzítettek lezárása a következő futásra marad: egy futás egy lépés.
    outcomes = resolve_entries(entries, series, forecasts, last_session)
    resolved = sum(1 for i, f in outcomes.items() if store.write(i, f, pin=False))
    counts = {"open": len(entries), "pinned": pinned, "resolved": resolved}
    log.info("scenario_resolve_done", **counts)
    return counts


def run_beside_journal(
    journal: object,
    storage: Storage,
    series: dict[str, pd.Series],
    forecasts: pd.DataFrame,
    last_session: date,
    display_prefix: str,
) -> None:
    """A napi kiértékelésből hívva; a hibája nem állíthatja meg a modell mérését."""
    store = SupabaseScenarios.beside(journal)
    if store is None:
        return
    try:
        run(store, storage, series, forecasts, last_session, display_prefix)
    except Exception as error:  # noqa: BLE001
        log.error("scenario_resolve_failed", error=type(error).__name__)
