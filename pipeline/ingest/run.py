"""A napi árfolyam-letöltés (spec/05, 5. fejezet: `ingest`, hétköznap 22:30 UTC).

Két mód:
- `daily`: az utolsó 10 kereskedési nap újra letöltve, összefésülve a friss év
  fájljával. Ha egy papírnál az ablakban új felosztás volt, annak a teljes
  múltja újra letöltődik, mert a forrás a záróárat visszamenőleg igazítja.
- `backfill`: a teljes múlt 2005-től, minden évfájl újraírva (első futás, és
  hetente egyszer a csendes eltérések ellen).

A futás hibával áll le, ha egyetlen papír is kimaradt: a csendes adathiány a
mérést hamisítaná meg, és a riasztásnak a tulajdonoshoz kell érnie, nem a
felhasználókhoz (spec/05, 8. fejezet).

Futtatás:
    uv run python -m pipeline.ingest.run --mode daily
    uv run python -m pipeline.ingest.run --mode backfill --local data   # próba, a gépen
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from pipeline import log as logging_setup
from pipeline.calendar import last_closed_session, sessions_back
from pipeline.config import DAILY_WINDOW_SESSIONS, HISTORY_START, RAW_BUCKET, load_settings
from pipeline.ingest.chain import ChainResult, NoDataError, ProviderChain
from pipeline.ingest.partitions import (
    ACTION_SCHEMA,
    ACTIONS_PATH,
    existing_years,
    from_parquet,
    read_partition,
    to_parquet,
    upsert,
    write_partitions,
)
from pipeline.ingest.providers.base import BaseProvider
from pipeline.ingest.providers.tiingo import TiingoProvider
from pipeline.ingest.providers.twelvedata import TwelveDataProvider
from pipeline.ingest.providers.yf import YFinanceProvider
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.ingest.validate import check_hard_rules, drop_off_session, drop_unclosed, mark_quality
from pipeline.universe import active_on, load_universe

log = logging_setup.get_logger(__name__)


def build_chain() -> ProviderChain:
    settings = load_settings()
    providers: list[BaseProvider] = [
        YFinanceProvider(),
        TiingoProvider(settings.tiingo_api_key),
        TwelveDataProvider(settings.twelve_data_api_key),
    ]
    return ProviderChain(providers)


def to_canonical(
    result: ChainResult, ids: dict[str, str], last: date, fetched_at: datetime
) -> tuple[pd.DataFrame, int]:
    """Tickerből belső azonosító, le nem zárt és zárvatartási napok nélkül, minőségjelöléssel."""
    frame = result.prices.copy()
    frame["instrument_id"] = frame["ticker"].map(ids)
    frame = frame.dropna(subset=["instrument_id"])
    frame = drop_unclosed(frame, last)
    frame, off_session = drop_off_session(frame)
    frame = frame.drop_duplicates(subset=["instrument_id", "date"], keep="first")
    frame["fetched_at"] = pd.Timestamp(fetched_at)
    frame = mark_quality(frame)
    check_hard_rules(frame, last)
    return frame.drop(columns=["ticker"]).reset_index(drop=True), off_session


def canonical_actions(result: ChainResult, ids: dict[str, str], fetched_at: datetime) -> pd.DataFrame:
    if result.actions.empty:
        return pd.DataFrame(columns=list(ACTION_SCHEMA.names))
    acts = result.actions.copy()
    acts["instrument_id"] = acts["ticker"].map(ids)
    acts["date"] = pd.to_datetime(acts["date"]).dt.tz_localize(None).dt.date
    acts["dividend"] = pd.to_numeric(acts["dividend"], errors="coerce").fillna(0.0)
    acts["split_ratio"] = pd.to_numeric(acts["split_ratio"], errors="coerce").fillna(0.0)
    acts["fetched_at"] = pd.Timestamp(fetched_at)
    return acts.dropna(subset=["instrument_id"]).loc[:, list(ACTION_SCHEMA.names)]


def new_split_instruments(actions: pd.DataFrame, storage: Storage) -> list[str]:
    """Azok a papírok, amelyeknél ÚJ felosztás van az ablakban.

    Felosztásnál a forrás a záróárat is visszamenőleg igazítja, ezért a papír
    teljes múltja újratöltődik. Osztaléknál nem kell: a teljes hozamot a
    záróárból és az osztaléklistából mi számoljuk (`pipeline.corporate`).
    A már tárolt eseményt nem dolgozzuk fel újra (különben egy felosztás
    miatt tíz egymást követő napon töltenénk le ugyanazt a múltat).
    """
    splits = actions[actions["split_ratio"] > 0] if not actions.empty else actions
    if splits.empty:
        return []
    stored = storage.download(RAW_BUCKET, ACTIONS_PATH)
    if stored is None:
        return sorted(set(splits["instrument_id"]))
    known = from_parquet(stored)
    seen = set(zip(known["instrument_id"], known["date"], strict=True))
    fresh = [i for i, d in zip(splits["instrument_id"], splits["date"], strict=True) if (i, d) not in seen]
    return sorted(set(fresh))


def run(mode: str, storage: Storage, now: datetime) -> dict[str, object]:
    fetched_at = now.astimezone(UTC)
    last = last_closed_session(now)
    # Az univerzum-tagság a futás napjára szól (valid_from/valid_to), nem a
    # letöltött időszakra: egy ma felvett papír teljes múltja is kell.
    universe = active_on(load_universe(), fetched_at.date())
    ids = dict(zip(universe["ticker"], universe["instrument_id"], strict=True))
    tickers = list(ids)
    start = HISTORY_START if mode == "backfill" else sessions_back(last, DAILY_WINDOW_SESSIONS)[0]

    storage.ensure_private_bucket(RAW_BUCKET)
    chain = build_chain()
    log.info(
        "ingest_start",
        mode=mode,
        tickers=len(tickers),
        start=start.isoformat(),
        last_session=last.isoformat(),
    )

    result = chain.fetch(tickers, start, last)
    fresh, off_session = to_canonical(result, ids, last, fetched_at)
    actions = canonical_actions(result, ids, fetched_at)

    refreshed: list[str] = []
    refresh_missing: list[str] = []
    if mode == "backfill":
        written = write_partitions(storage, fresh)
    else:
        event_ids = new_split_instruments(actions, storage)
        if event_ids:
            by_id = {v: k for k, v in ids.items()}
            full = chain.fetch([by_id[i] for i in event_ids], HISTORY_START, last)
            full_frame, extra_off = to_canonical(full, ids, last, fetched_at)
            off_session += extra_off
            refreshed = sorted(set(full_frame["instrument_id"]))
            # Ami nem töltődött le újra, annak a régi sorai maradnak — ez látszik a jelentésben.
            refresh_missing = full.report.missing
            years = sorted(set(existing_years(storage)) | {d.year for d in full_frame["date"]})
        else:
            full_frame = fresh.iloc[0:0]
            years = sorted({d.year for d in fresh["date"]})

        written = []
        for year in years:
            current = read_partition(storage, year)
            in_year = fresh[[d.year == year for d in fresh["date"]]]
            full_in_year = full_frame[[d.year == year for d in full_frame["date"]]]
            merged = upsert(
                current,
                pd.concat([in_year, full_in_year]).drop_duplicates(["instrument_id", "date"], keep="last"),
                refreshed,
            )
            if not merged.empty:
                written += write_partitions(storage, merged)

    if not actions.empty:
        existing = storage.download(RAW_BUCKET, ACTIONS_PATH)
        old = from_parquet(existing) if existing else actions.iloc[0:0]
        merged_actions = (
            pd.concat([old, actions], ignore_index=True)
            .drop_duplicates(subset=["instrument_id", "date"], keep="last")
            .sort_values(["instrument_id", "date"])
        )
        storage.upload(
            RAW_BUCKET, ACTIONS_PATH, to_parquet(merged_actions, ACTION_SCHEMA), "application/octet-stream"
        )

    # Az összefoglalóban csak darabszám és forrásnév van — ár soha (a napló publikus).
    summary: dict[str, object] = {
        "mode": mode,
        "run_at": fetched_at.isoformat(timespec="seconds"),
        "last_session": last.isoformat(),
        "window_start": start.isoformat(),
        "instruments": len(tickers),
        "rows": len(fresh),
        "suspect_rows": int((fresh["quality"] == "suspect").sum()),
        "off_session_rows_dropped": off_session,
        "corporate_action_events": len(actions),
        "refreshed_instruments": len(refreshed),
        "refresh_missing": refresh_missing,
        "partitions_written": sorted(set(written)),
        **result.report.as_dict(),
    }
    storage.upload(
        RAW_BUCKET,
        f"runs/ingest/{last.isoformat()}-{mode}.json",
        json.dumps(summary, indent=2).encode(),
        "application/json",
    )
    return summary


def write_step_summary(summary: dict[str, object]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    served = summary.get("tickers_by_source", {})
    served_text = ", ".join(f"{k}: {v}" for k, v in served.items()) if isinstance(served, dict) else "-"
    lines = [
        f"### Árfolyam-letöltés — {summary['mode']}, session {summary['last_session']}",
        "",
        "| | |",
        "|---|---|",
        f"| Instrumentum | {summary['instruments']} |",
        f"| Sor | {summary['rows']} |",
        f"| Kiszolgálta | {served_text} |",
        f"| Kimaradt | {len(summary['missing']) if isinstance(summary['missing'], list) else '-'} |",
        f"| Gyanús sor (megjelölve) | {summary['suspect_rows']} |",
        f"| Újraigazított papír | {summary['refreshed_instruments']} |",
        f"| Megírt évek | {summary['partitions_written']} |",
    ]
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze napi árfolyam-letöltés")
    parser.add_argument("--mode", choices=["daily", "backfill"], default="daily")
    parser.add_argument("--local", type=Path, help="helyi mappa a privát tár helyett (próbafuttatás)")
    parser.add_argument("--now", help="ISO időpont UTC-ben (teszthez); alapból a mostani idő")
    args = parser.parse_args(argv)

    logging_setup.configure()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)

    if args.local:
        storage: Storage = LocalStorage(args.local)
    else:
        settings = load_settings()
        if not settings.storage_configured or not settings.supabase_url or not settings.supabase_secret_key:
            log.error(
                "storage_not_configured", hint="SUPABASE_URL és SUPABASE_SECRET_KEY kell (GitHub Secrets)"
            )
            return 2
        storage = SupabaseStorage(settings.supabase_url, settings.supabase_secret_key)

    try:
        summary = run(args.mode, storage, now)
    except NoDataError as error:
        log.error("ingest_failed_no_data", error=str(error))
        return 1

    write_step_summary(summary)
    log.info(
        "ingest_done",
        rows=summary["rows"],
        missing=len(summary["missing"]) if isinstance(summary["missing"], list) else None,
        sources=summary["tickers_by_source"],
    )
    if summary["missing"]:
        log.error("ingest_incomplete", missing=summary["missing"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
