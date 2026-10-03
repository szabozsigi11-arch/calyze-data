"""A kötvény napi becslése és lenyomata (`docs/kotveny.md`, 6. fejezet).

A kripto becslés-építőjét használja (`pipeline.crypto.forecast.build`) a
„hozam-áron”, majd a szint-mezőket visszaírja hozamra (%): a felület hozamot
mutat, a sáv és a várható érték a hozam szintjén értelmes. Csak a 15:30-as
(ET) felvétel után 6 órán belül készült becslés élő.

Futtatás:
    uv run python -m pipeline.bonds.forecast --manifest-dir manifests-bonds
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import log as logging_setup
from pipeline.bonds.calendar import last_bond_day, offset, snapshot_at
from pipeline.bonds.features import CALENDAR, as_price, bond_regime, build_bond_features, load_bond_yields
from pipeline.bonds.model import FAMILY, MODEL_PREFIX, VERSION
from pipeline.config import RAW_BUCKET, load_settings
from pipeline.crypto.forecast import build, manifest_entry
from pipeline.features.run import MACRO_PATH, _read_table
from pipeline.forecast.run import MIN_SESSION_COVERAGE, _package_bytes
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.model.config import HORIZONS
from pipeline.universe import active_on, load_bonds_universe

log = logging_setup.get_logger(__name__)

PREFIX = "forecasts-bonds"
LOOKBACK_YEARS = 3
MAX_DELAY = timedelta(hours=6)
LEVEL_COLUMNS = ("close", "price_low", "price_high", "expected_price")


def package_path(day: date) -> str:
    return f"{PREFIX}/{day.year}/{day.isoformat()}.parquet"


def too_late(day: date, now: datetime) -> bool:
    """A 15:30-as (ET) felvétel után 6 óránál később készült becslés nem számít élőnek."""
    return now.astimezone(UTC) - snapshot_at(day) > MAX_DELAY


def to_yield(frame: pd.DataFrame) -> pd.DataFrame:
    """A szint-mezők az `exp(hozam/100)` „árból” vissza hozamra (%), pontosan."""
    out = frame.copy()
    for col in LEVEL_COLUMNS:
        out[col] = 100.0 * np.log(out[col].astype("float64"))
    return out


def load_models(storage: Storage) -> dict[int, dict[str, object]]:
    models: dict[int, dict[str, object]] = {}
    for horizon in HORIZONS:
        blob = storage.download(RAW_BUCKET, f"{MODEL_PREFIX}/h{horizon}.pkl")
        if blob is None:
            raise RuntimeError(
                "Nincs betanított kötvény-modell — előbb: python -m pipeline.bonds.model --task train"
            )
        models[horizon] = pickle.loads(blob)  # noqa: S301 — saját, privát tárból származó fájl
    return models


def run(storage: Storage, now: datetime, dry_run: bool = False) -> dict[str, object]:
    day = last_bond_day(now)
    if too_late(day, now):
        log.warning("bonds_forecast_too_late", day=str(day))
        return {"session": str(day), "status": "too_late"}
    if storage.download(RAW_BUCKET, package_path(day)) is not None:
        return {"session": str(day), "status": "already_saved"}
    universe = active_on(load_bonds_universe(), now.astimezone(UTC).date())
    yields = load_bond_yields(storage, list(range(day.year - LOOKBACK_YEARS, day.year + 1)))
    yields = yields[yields["date"] <= day]
    covered = yields[yields["date"] == day]["instrument_id"].nunique()
    if covered < MIN_SESSION_COVERAGE * len(universe):
        # A görbe még nincs közzétéve (vagy hiányos): régebbi napra nem becslünk.
        log.warning("bonds_forecast_no_curve", day=str(day), covered=int(covered))
        return {"session": str(day), "status": "no_curve"}
    regime = bond_regime(yields, universe)
    macro = _read_table(storage, MACRO_PATH)
    if macro is not None:
        macro = macro.set_index("date")
    features = build_bond_features(yields, universe, regime, macro)
    prices = as_price(yields)
    frame = build(
        features,
        prices,
        day,
        load_models(storage),
        now.astimezone(UTC),
        family=FAMILY,
        version=VERSION,
        calendar=CALENDAR,
        target=offset,
    )
    frame = to_yield(frame)
    # A sokk-jel a csomagba kerül, a lenyomat alá (7. fejezet).
    from pipeline.bonds.shocks import attach

    frame = attach(frame, prices, universe, day)
    package = _package_bytes(frame)
    entry = manifest_entry(day, package, frame, now.astimezone(UTC), len(universe), FAMILY, VERSION, CALENDAR)
    if dry_run:
        return {**entry, "status": "dry_run"}
    storage.upload(RAW_BUCKET, package_path(day), package, "application/octet-stream")
    storage.upload(
        RAW_BUCKET,
        f"runs/forecast-bonds/{day.isoformat()}.json",
        json.dumps(entry, indent=2).encode(),
        "application/json",
    )
    log.info("bonds_forecast_saved", **entry)
    return {**entry, "status": "saved"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze kötvény napi becslés")
    parser.add_argument("--local", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--manifest-dir", type=Path)
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
    result = run(storage, datetime.now(UTC), dry_run=args.dry_run)
    if args.manifest_dir and result.get("status") == "saved":
        day = date.fromisoformat(str(result["session"]))
        out = args.manifest_dir / str(day.year)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{day.isoformat()}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
