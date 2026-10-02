"""A deviza napi letöltése az EKB referencia-árfolyamából (`docs/fx-univerzum.md`).

Az EKB a hét nem-euró devizát az euró ellen közli; a 28 pár ebből
keresztárfolyamként áll elő: `A/B = (B per EUR) / (A per EUR)`. Naponta egy
árfolyam (a 14:10 CET-es fixálás): a négy ár ugyanaz, volumen nincs.

Külön fájlokba ír (`prices_fx_daily/`), mint a kripto. Ha egy TARGET-napra
nincs közölt árfolyam, az hiányként látszik, nem pótoljuk.

Futtatás:
    uv run python -m pipeline.ingest.fx --mode daily
    uv run python -m pipeline.ingest.fx --mode backfill --local data
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from pipeline import log as logging_setup
from pipeline.config import RAW_BUCKET, load_settings
from pipeline.fx.calendar import last_fixing_day, target_days
from pipeline.ingest.partitions import read_partition, upsert, write_partitions
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.ingest.validate import mark_quality
from pipeline.universe import active_on, load_fx_universe

log = logging_setup.get_logger(__name__)

FX_PRICES_PREFIX = "prices_fx_daily"
CURRENCIES = ("USD", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD")
ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{codes}.EUR.SP00.A"
FX_HISTORY_START = date(1999, 1, 4)
#: A napi futás ennyi naptári napot kér újra (a késve javított értékek miatt).
DAILY_WINDOW_DAYS = 21


class ECBError(RuntimeError):
    """Az EKB nem adott használható választ."""


def fetch_ecb(start: date, end: date, timeout: float = 60) -> pd.DataFrame:
    """Hosszú tábla: date, currency, per_eur."""
    url = ECB_URL.format(codes="+".join(CURRENCIES))
    params = {"format": "csvdata", "startPeriod": start.isoformat(), "endPeriod": end.isoformat()}
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers={"Accept": "text/csv"})
        except requests.RequestException as error:
            if attempt == 2:
                raise ECBError(type(error).__name__) from error
            continue
        if r.status_code == 200:
            raw = pd.read_csv(io.StringIO(r.text), usecols=["CURRENCY", "TIME_PERIOD", "OBS_VALUE"])
            out = raw.rename(columns={"CURRENCY": "currency", "TIME_PERIOD": "date", "OBS_VALUE": "per_eur"})
            out["date"] = pd.to_datetime(out["date"]).dt.date
            return out.dropna(subset=["per_eur"])
        if r.status_code == 404:
            return pd.DataFrame(columns=["date", "currency", "per_eur"])
    raise ECBError(f"HTTP {r.status_code}")


def cross_rates(ecb: pd.DataFrame, universe: pd.DataFrame, fetched_at: datetime) -> pd.DataFrame:
    """A 28 pár a kanonikus ár-sémában (a négy ár = a fixálás, volumen nincs)."""
    wide = ecb.pivot_table(index="date", columns="currency", values="per_eur", aggfunc="first")
    wide["EUR"] = 1.0
    rows = []
    for r in universe.itertuples():
        base, quote = str(r.source_symbol).split("/")
        if base not in wide or quote not in wide:
            continue
        rate = (wide[quote] / wide[base]).dropna()
        rows.append(
            pd.DataFrame({"instrument_id": r.instrument_id, "date": rate.index, "rate": rate.to_numpy()})
        )
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    frame = pd.DataFrame(
        {
            "instrument_id": out["instrument_id"],
            "date": out["date"],
            "open": out["rate"],
            "high": out["rate"],
            "low": out["rate"],
            "close": out["rate"],
            "adj_close": out["rate"],
            "volume": np.nan,
            "source": "ecb",
            "fetched_at": pd.Timestamp(fetched_at),
        }
    )
    return mark_quality(frame).sort_values(["instrument_id", "date"]).reset_index(drop=True)


def missing_days(ecb: pd.DataFrame, start: date, last: date) -> list[str]:
    """TARGET-napok, amelyekre az EKB egyetlen devizára sem közölt árfolyamot."""
    have = set(ecb["date"])
    return [d.isoformat() for d in target_days(start, last) if d not in have]


def run(mode: str, storage: Storage, now: datetime) -> dict[str, object]:
    fetched_at = now.astimezone(UTC)
    last = last_fixing_day(now)
    universe = active_on(load_fx_universe(), fetched_at.date())
    start = FX_HISTORY_START if mode == "backfill" else last - timedelta(days=DAILY_WINDOW_DAYS)
    storage.ensure_private_bucket(RAW_BUCKET)
    ecb = fetch_ecb(start, last)
    ecb = ecb[ecb["date"] <= last]
    fresh = cross_rates(ecb, universe, fetched_at)
    if fresh.empty:
        raise ECBError("az EKB-ből egyetlen pár sem állt elő")
    gaps = missing_days(ecb, max(start, min(ecb["date"])), last) if not ecb.empty else []

    if mode == "backfill":
        written = write_partitions(storage, fresh, FX_PRICES_PREFIX)
    else:
        written = []
        for year in sorted({d.year for d in fresh["date"]}):
            current = read_partition(storage, year, FX_PRICES_PREFIX)
            merged = upsert(current, fresh[[d.year == year for d in fresh["date"]]])
            if not merged.empty:
                written += write_partitions(storage, merged, FX_PRICES_PREFIX)

    summary: dict[str, object] = {
        "asset_class": "fx",
        "mode": mode,
        "run_at": fetched_at.isoformat(timespec="seconds"),
        "last_fixing": last.isoformat(),
        "pairs": int(fresh["instrument_id"].nunique()),
        "rows": len(fresh),
        "missing_target_days": gaps,
        "partitions_written": sorted(set(written)),
        "source": "ecb",
    }
    storage.upload(
        RAW_BUCKET,
        f"runs/ingest-fx/{last.isoformat()}-{mode}.json",
        json.dumps(summary, indent=2).encode(),
        "application/json",
    )
    log.info(
        "fx_ingest_done", **{k: v for k, v in summary.items() if k != "missing_target_days"}, gaps=len(gaps)
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze deviza-letöltés (EKB)")
    parser.add_argument("--mode", choices=["daily", "backfill"], default="daily")
    parser.add_argument("--local", type=Path)
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
    try:
        summary = run(args.mode, storage, datetime.now(UTC))
    except ECBError as error:
        log.error("fx_ingest_failed", error=str(error))
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
