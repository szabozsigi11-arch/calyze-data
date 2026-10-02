"""A kripto megjelenítési fájljai (5. fázis, E4).

Saját fájlokba ír (`crypto/…`, `record-crypto/…`): a napi adatfrissítés az app
élesítésétől függetlenül fut, és a mostani felület a kriptót nem ismeri. Ha a
kripto a meglévő listákba kerülne, jelölés nélkül keveredne a részvényekkel.
A papír-csomag (`instruments/CZ006xx.json`) és a munkaasztal idősora ugyanazzal
az építővel készül, mint a részvényeké — a felület ugyanúgy olvassa.

Futtatás:
    uv run python -m pipeline.crypto.publish
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
from pipeline.config import load_settings
from pipeline.crypto.features import CALENDAR, load_crypto_prices
from pipeline.crypto.model import BACKTEST_PATH, FAMILY, VERSION
from pipeline.crypto.resolve import FIRST_YEAR, LIVE_PATH, load_forecasts, load_outcomes
from pipeline.features.run import _read_table
from pipeline.ingest.crypto import CRYPTO_HISTORY_START
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.publish.record import build_record
from pipeline.publish.run import (
    DISPLAY_BUCKET,
    _dumps,
    build_arena,
    build_history,
    build_index,
    build_instrument,
    screener_row,
)
from pipeline.universe import active_on, load_crypto_universe

log = logging_setup.get_logger(__name__)

PREFIX = "crypto"
EXPORT_PREFIX = "record-crypto"
#: A papír-nézet chartja ennyi napot mutat (a részvényeknél 250 session ≈ 1 év).
HISTORY_DAYS = 365


def _latest(
    day: str,
    today: pd.DataFrame,
    outcomes: pd.DataFrame,
    universe: int,
    first_live: str | None,
    now: datetime,
) -> dict[str, object]:
    resolved: dict[str, object] = {"count": 0}
    if not outcomes.empty and "resolved_at" in outcomes:
        stamp = pd.to_datetime(outcomes["resolved_at"])
        recent = outcomes[stamp == stamp.max()]
        resolved = {
            "count": len(recent),
            "hits": int(recent["hit"].sum()),
            "baseline_hits": int(recent["baseline_hit"].sum()),
            "on": str(recent["target_session"].max()),
        }
    regime = None
    if not today.empty and "regime" in today and not today["regime"].dropna().empty:
        regime = str(today["regime"].dropna().mode().iloc[0])
    return {
        "generated_at": now.isoformat(),
        "session": day,
        "calendar": CALENDAR,
        "model": f"{FAMILY} {VERSION}",
        "regime": regime,
        "instruments_with_forecast": int(today["instrument_id"].nunique()) if not today.empty else 0,
        "universe": universe,
        "resolved": resolved,
        # Az élő rekord innen számít (docs/kripto-modell.md, 6.).
        "live_from": first_live,
    }


def run(storage: Storage, now: datetime, dry_run: bool = False) -> dict[str, object]:
    last = last_closed_session(now, CALENDAR)
    universe = active_on(load_crypto_universe(), now.astimezone(UTC).date())
    prices = load_crypto_prices(storage, list(range(CRYPTO_HISTORY_START.year, last.year + 1)))
    forecasts = load_forecasts(storage, list(range(FIRST_YEAR, last.year + 1)))
    outcomes = load_outcomes(storage, list(range(FIRST_YEAR, last.year + 1)))

    if forecasts.empty:
        day, today, first_live = str(last), pd.DataFrame(columns=["instrument_id"]), None
    else:
        newest = max(forecasts["session"])
        day, today, first_live = (
            str(newest),
            forecasts[forecasts["session"] == newest],
            str(min(forecasts["session"])),
        )

    files: list[tuple[str, bytes, str]] = []

    def add(path: str, payload: object) -> None:
        files.append((path, _dumps(payload), "application/json"))

    add(f"{PREFIX}/latest.json", _latest(day, today, outcomes, len(universe), first_live, now))
    index = build_index(universe, today, prices)
    add(f"{PREFIX}/instruments.json", [{**row, "calendar": CALENDAR} for row in index])

    live = _read_table(storage, LIVE_PATH)
    backtest = _read_table(storage, BACKTEST_PATH)
    add(
        f"{PREFIX}/evidence.json",
        {
            "generated_at": now.isoformat(),
            "calendar": CALENDAR,
            "live_from": first_live,
            "live": build_arena(live if live is not None else pd.DataFrame()),
            "backtest": build_arena(backtest if backtest is not None else pd.DataFrame()),
        },
    )

    existing = set() if dry_run else set(storage.list(DISPLAY_BUCKET, EXPORT_PREFIX))
    record, record_files = build_record(outcomes, forecasts, universe, existing, now, EXPORT_PREFIX)
    add(f"{PREFIX}/record.json", record)
    files.extend(record_files)

    by_price = {i: g for i, g in prices.groupby("instrument_id")}
    by_today = {i: g for i, g in today.groupby("instrument_id")} if not today.empty else {}
    by_outcome = {i: g for i, g in outcomes.groupby("instrument_id")} if not outcomes.empty else {}
    history_all = (
        forecasts if not forecasts.empty else pd.DataFrame(columns=["instrument_id", "session", "horizon"])
    )
    by_history = {i: g for i, g in history_all.groupby("instrument_id")}
    screener = []
    for row in universe.to_dict("records"):
        iid = str(row["instrument_id"])
        meta = {
            "id": iid,
            "ticker": row["ticker"],
            "name": row["name"],
            "asset_class": "crypto",
            "sector": None,
            "exchange_calendar": CALENDAR,
        }
        bars = by_price.get(iid, prices.iloc[0:0])
        payload = build_instrument(
            meta=meta,
            prices=bars.tail(HISTORY_DAYS),
            forecasts=by_today.get(iid, pd.DataFrame()),
            history=by_history.get(iid, pd.DataFrame(columns=["session", "horizon"])),
            outcomes=by_outcome.get(iid, pd.DataFrame()),
            session=pd.Timestamp(day).date(),
        )
        add(f"instruments/{iid}.json", payload)
        if not bars.empty:
            add(f"history/{iid}.json", build_history(bars))
        screener.append(
            screener_row(
                {k: meta[k] for k in ("id", "ticker", "name", "sector", "asset_class")},
                bars,
                by_today.get(iid, pd.DataFrame()),
                by_outcome.get(iid, pd.DataFrame(columns=["brier", "baseline_brier"])),
            )
        )
    add(f"{PREFIX}/screener.json", {"session": day, "rows": screener})

    if dry_run:
        return {"files": len(files), "status": "dry_run"}
    storage.ensure_private_bucket(DISPLAY_BUCKET)
    for path, blob, content_type in files:
        storage.upload(DISPLAY_BUCKET, path, blob, content_type)
    log.info("crypto_publish_done", files=len(files), day=day)
    return {"files": len(files), "day": day, "status": "published"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze kripto megjelenítési fájlok")
    parser.add_argument("--local", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging_setup.configure()
    if args.local:
        storage: Storage = LocalStorage(args.local)
    else:
        settings = load_settings()
        if not settings.supabase_url or not settings.supabase_secret_key:
            log.error("storage_not_configured")
            return 2
        storage = SupabaseStorage(settings.supabase_url, settings.supabase_secret_key)
    print(json.dumps(run(storage, datetime.now(UTC), args.dry_run), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
