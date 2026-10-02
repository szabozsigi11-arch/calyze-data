"""A kripto-becslések és kripto-tézisek kiértékelése (5. fázis, E4).

Ugyanaz a lezárás, mint a részvényeknél (`pipeline.resolve.run.resolve_due`):
a becslés sora nem módosul, a kimenetel külön sorban keletkezik, egyszer. A
kripto saját táblákba ír (`outcomes-crypto/`, `arena/crypto_live.parquet`), és
a mérési rekordjai saját családot alkotnak (`scope = crypto`), saját
FDR-korrekcióval (`docs/kripto-modell.md`, 5.).

Futtatás:
    uv run python -m pipeline.crypto.resolve
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from pipeline import log as logging_setup
from pipeline.calendar import last_closed_session
from pipeline.config import RAW_BUCKET, load_settings
from pipeline.crypto.features import CALENDAR, EMPTY_ACTIONS, load_crypto_prices
from pipeline.crypto.forecast import PREFIX
from pipeline.crypto.model import SCOPE
from pipeline.features.run import _read_table, _write_table
from pipeline.ingest.crypto import CRYPTO_HISTORY_START
from pipeline.ingest.partitions import from_parquet
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.journal import resolve as journal_resolve
from pipeline.resolve.run import live_arena, resolve_due

log = logging_setup.get_logger(__name__)

OUTCOMES_PREFIX = "outcomes-crypto"
LIVE_PATH = "arena/crypto_live.parquet"
#: Az első kripto-becslés éve; előtte nincs mit betölteni.
FIRST_YEAR = 2026


def outcomes_path(year: int) -> str:
    return f"{OUTCOMES_PREFIX}/year={year}.parquet"


def load_forecasts(storage: Storage, years: list[int]) -> pd.DataFrame:
    frames = []
    for year in years:
        for path in storage.list(RAW_BUCKET, f"{PREFIX}/{year}"):
            blob = storage.download(RAW_BUCKET, path)
            if blob is not None:
                frames.append(from_parquet(blob))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_outcomes(storage: Storage, years: list[int]) -> pd.DataFrame:
    frames = [f for f in (_read_table(storage, outcomes_path(y)) for y in years) if f is not None]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def crypto_live_arena(outcomes: pd.DataFrame) -> pd.DataFrame:
    """A részvényes élő rekord-építő, a kripto saját családjaként."""
    arena = live_arena(outcomes)
    if arena.empty:
        return arena
    return arena.assign(scope=SCOPE)


def run(
    storage: Storage, now: datetime, journal: journal_resolve.JournalStore | None = None
) -> dict[str, object]:
    last = last_closed_session(now, CALENDAR)
    years = list(range(FIRST_YEAR, last.year + 1))
    forecasts = load_forecasts(storage, years)
    prices = load_crypto_prices(
        storage, list(range(max(CRYPTO_HISTORY_START.year, last.year - 1), last.year + 1))
    )

    summary: dict[str, object] = {"asset_class": "crypto", "last_day": last.isoformat()}
    if not forecasts.empty:
        known = load_outcomes(storage, years)
        done = set(known["forecast_id"]) if not known.empty else set()
        pending = forecasts[~forecasts["forecast_id"].isin(done)]
        fresh = resolve_due(pending, prices, EMPTY_ACTIONS, last, now.astimezone(UTC))
        outcomes = pd.concat([known, fresh], ignore_index=True) if not fresh.empty else known
        if not fresh.empty:
            for year in sorted({d.year for d in outcomes["session"]}):
                part = outcomes[[d.year == year for d in outcomes["session"]]].reset_index(drop=True)
                _write_table(storage, outcomes_path(year), part)
        arena = crypto_live_arena(outcomes)
        if not arena.empty:
            _write_table(storage, LIVE_PATH, arena)
        summary |= {
            "resolved_now": len(fresh),
            "resolved_total": len(outcomes),
            "open": int(len(forecasts) - len(outcomes)),
            "live_records": len(arena),
        }
    else:
        summary |= {"resolved_now": 0, "resolved_total": 0, "open": 0, "live_records": 0}

    # A kripto-tézisek: csak a kripto árfolyamával és naptárával. A tézisek
    # hibája nem állíthatja meg a modell mérését (mint a részvényeknél).
    if journal is not None and not prices.empty:
        try:
            series = journal_resolve.as_series(prices.assign(tr=prices["close"]))
            journal_resolve.run(journal, series, forecasts, last, CALENDAR)
        except Exception as error:  # noqa: BLE001
            log.error("crypto_journal_resolve_failed", error=type(error).__name__)

    storage.upload(
        RAW_BUCKET,
        f"runs/resolve-crypto/{last.isoformat()}.json",
        json.dumps(summary, indent=2, default=str).encode(),
        "application/json",
    )
    log.info("crypto_resolve_done", **summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze kripto-kiértékelés")
    parser.add_argument("--local", type=Path)
    args = parser.parse_args(argv)
    logging_setup.configure()
    settings = load_settings()
    journal: journal_resolve.JournalStore | None = None
    if args.local:
        storage: Storage = LocalStorage(args.local)
    elif settings.supabase_url and settings.supabase_secret_key:
        storage = SupabaseStorage(settings.supabase_url, settings.supabase_secret_key)
        journal = journal_resolve.SupabaseJournal(settings.supabase_url, settings.supabase_secret_key)
    else:
        log.error("storage_not_configured")
        return 2
    print(json.dumps(run(storage, datetime.now(UTC), journal), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
