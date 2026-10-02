"""A kripto napi letöltése (`docs/kripto-univerzum.md`, 5. fejezet).

Külön ág a részvényes letöltés mellett, külön fájlokba
(`prices_crypto_daily/`): a részvényes rétegek így egyetlen 24/7-es sort sem
látnak. A nap UTC 00:00–24:00 (a `24/7` naptár); a még le nem zárt mai nap
nem kerül be.

A hiányzó napot nem pótoljuk és nem töltjük ki: hiányként jelenik meg a futás
jelentésében. Ha egy papír egyáltalán nem jött le, a futás hibával áll le, mint
a részvényeknél — a csendes adathiány a mérést hamisítaná meg.

Forrás: csak a Yahoo. A tartalék források más szimbólumot és más napi zárást
használhatnak; amíg nem ellenőriztük, hogy ugyanazt a UTC-napot adják,
kriptóra nem lépnek be.

Futtatás:
    uv run python -m pipeline.ingest.crypto --mode daily
    uv run python -m pipeline.ingest.crypto --mode backfill --local data
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from pipeline import log as logging_setup
from pipeline.calendar import last_closed_session, sessions_back
from pipeline.config import DAILY_WINDOW_SESSIONS, RAW_BUCKET, load_settings
from pipeline.ingest.chain import NoDataError, ProviderChain
from pipeline.ingest.partitions import (
    CRYPTO_PRICES_PREFIX,
    read_partition,
    upsert,
    write_partitions,
)
from pipeline.ingest.providers.yf import YFinanceProvider
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.ingest.validate import check_hard_rules, drop_unclosed, mark_quality
from pipeline.universe import active_on, load_crypto_universe

log = logging_setup.get_logger(__name__)

CALENDAR = "24/7"
#: A Yahoo legkorábbi kripto-gyertyája (BTC-USD); előtte nincs mit kérni.
CRYPTO_HISTORY_START = date(2014, 9, 17)


def build_chain() -> ProviderChain:
    return ProviderChain([YFinanceProvider()])


def canonical(prices: pd.DataFrame, ids: dict[str, str], last: date, fetched_at: datetime) -> pd.DataFrame:
    """Szimbólumból belső azonosító; a hétvége is kereskedési nap, tehát marad."""
    frame = prices.copy()
    frame["instrument_id"] = frame["ticker"].map(ids)
    frame = frame.dropna(subset=["instrument_id"])
    frame = drop_unclosed(frame, last)
    frame = frame.drop_duplicates(subset=["instrument_id", "date"], keep="first")
    frame["fetched_at"] = pd.Timestamp(fetched_at)
    frame = mark_quality(frame)
    check_hard_rules(frame, last)
    return frame.drop(columns=["ticker"]).sort_values(["instrument_id", "date"]).reset_index(drop=True)


def missing_days(frame: pd.DataFrame, start: date, last: date) -> dict[str, int]:
    """Papíronként a hiányzó UTC-napok száma az ablakban.

    Az ablak a papír első napjánál kezdődik, ha az későbbi: egy 2020-ban
    indult eszköznek nincs 2015-ös hiánya.
    """
    out: dict[str, int] = {}
    for instrument, part in frame.groupby("instrument_id"):
        first = max(start, min(part["date"]))
        expected = pd.date_range(first, last, freq="D").date
        n = len(set(expected) - set(part["date"]))
        if n:
            out[str(instrument)] = n
    return out


def run(mode: str, storage: Storage, now: datetime) -> dict[str, object]:
    fetched_at = now.astimezone(UTC)
    last = last_closed_session(now, CALENDAR)
    universe = active_on(load_crypto_universe(), fetched_at.date())
    ids = dict(zip(universe["source_symbol"], universe["instrument_id"], strict=True))
    start = (
        CRYPTO_HISTORY_START
        if mode == "backfill"
        else sessions_back(last, DAILY_WINDOW_SESSIONS, CALENDAR)[0]
    )

    storage.ensure_private_bucket(RAW_BUCKET)
    log.info(
        "crypto_ingest_start", mode=mode, instruments=len(ids), start=start.isoformat(), last=last.isoformat()
    )
    result = build_chain().fetch(list(ids), start, last)
    fresh = canonical(result.prices, ids, last, fetched_at)
    gaps = missing_days(fresh, start, last)

    if mode == "backfill":
        written = write_partitions(storage, fresh, CRYPTO_PRICES_PREFIX)
    else:
        written = []
        for year in sorted({d.year for d in fresh["date"]}):
            current = read_partition(storage, year, CRYPTO_PRICES_PREFIX)
            in_year = fresh[[d.year == year for d in fresh["date"]]]
            merged = upsert(current, in_year)
            if not merged.empty:
                written += write_partitions(storage, merged, CRYPTO_PRICES_PREFIX)

    # Csak darabszám és forrásnév — ár soha (a napló publikus).
    summary: dict[str, object] = {
        "asset_class": "crypto",
        "mode": mode,
        "run_at": fetched_at.isoformat(timespec="seconds"),
        "last_session": last.isoformat(),
        "window_start": start.isoformat(),
        "instruments": len(ids),
        "rows": len(fresh),
        "suspect_rows": int((fresh["quality"] == "suspect").sum()),
        "missing_days": gaps,
        "partitions_written": sorted(set(written)),
        **result.report.as_dict(),
    }
    storage.upload(
        RAW_BUCKET,
        f"runs/ingest-crypto/{last.isoformat()}-{mode}.json",
        json.dumps(summary, indent=2).encode(),
        "application/json",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze kripto-letöltés")
    parser.add_argument("--mode", choices=["daily", "backfill"], default="daily")
    parser.add_argument("--local", type=Path, help="helyi mappa a privát tár helyett (próbafuttatás)")
    parser.add_argument("--now", help="ISO időpont UTC-ben (teszthez)")
    args = parser.parse_args(argv)

    logging_setup.configure()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    if args.local:
        storage: Storage = LocalStorage(args.local)
    else:
        settings = load_settings()
        if not settings.supabase_url or not settings.supabase_secret_key:
            log.error("storage_not_configured")
            return 2
        storage = SupabaseStorage(settings.supabase_url, settings.supabase_secret_key)

    try:
        summary = run(args.mode, storage, now)
    except NoDataError as error:
        log.error("crypto_ingest_failed_no_data", error=str(error))
        return 1
    log.info(
        "crypto_ingest_done",
        rows=summary["rows"],
        missing=len(summary["missing"]) if isinstance(summary["missing"], list) else None,
        gap_instruments=len(summary["missing_days"]) if isinstance(summary["missing_days"], dict) else None,
    )
    if summary["missing"]:
        log.error("crypto_ingest_incomplete", missing=summary["missing"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
