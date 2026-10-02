"""A deviza napi becslése és lenyomata (`docs/fx-modell.md`, 5. fejezet).

A kripto becslés-építőjét használja (`pipeline.crypto.forecast.build`), a
deviza családjával és TARGET-célnappal. Csak a fixálás után 6 órán belül
készült becslés élő; a kimaradt nap nem pótolható.

Futtatás:
    uv run python -m pipeline.fx.forecast --manifest-dir manifests-fx
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pipeline import log as logging_setup
from pipeline.config import RAW_BUCKET, load_settings
from pipeline.crypto.forecast import build, manifest_entry
from pipeline.features.run import MACRO_PATH, _read_table
from pipeline.forecast.run import MIN_SESSION_COVERAGE, _package_bytes
from pipeline.fx.calendar import fixing_at, last_fixing_day, offset
from pipeline.fx.features import CALENDAR, build_fx_features, fx_regime, load_fx_prices
from pipeline.fx.model import FAMILY, MODEL_PREFIX, VERSION
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.model.config import HORIZONS
from pipeline.universe import active_on, load_fx_universe

log = logging_setup.get_logger(__name__)

PREFIX = "forecasts-fx"
LOOKBACK_YEARS = 3
MAX_DELAY = timedelta(hours=6)


def package_path(day: date) -> str:
    return f"{PREFIX}/{day.year}/{day.isoformat()}.parquet"


def too_late(day: date, now: datetime) -> bool:
    """A fixálás (14:10 CET) után 6 óránál később készült becslés nem számít élőnek."""
    return now.astimezone(UTC) - fixing_at(day) > MAX_DELAY


def load_models(storage: Storage) -> dict[int, dict[str, object]]:
    models: dict[int, dict[str, object]] = {}
    for horizon in HORIZONS:
        blob = storage.download(RAW_BUCKET, f"{MODEL_PREFIX}/h{horizon}.pkl")
        if blob is None:
            raise RuntimeError(
                "Nincs betanított deviza-modell — előbb: python -m pipeline.fx.model --task train"
            )
        models[horizon] = pickle.loads(blob)  # noqa: S301 — saját, privát tárból származó fájl
    return models


def run(storage: Storage, now: datetime, dry_run: bool = False) -> dict[str, object]:
    day = last_fixing_day(now)
    if too_late(day, now):
        log.warning("fx_forecast_too_late", day=str(day))
        return {"session": str(day), "status": "too_late"}
    if storage.download(RAW_BUCKET, package_path(day)) is not None:
        return {"session": str(day), "status": "already_saved"}
    universe = active_on(load_fx_universe(), now.astimezone(UTC).date())
    prices = load_fx_prices(storage, list(range(day.year - LOOKBACK_YEARS, day.year + 1)))
    prices = prices[prices["date"] <= day]
    covered = prices[prices["date"] == day]["instrument_id"].nunique()
    if covered < MIN_SESSION_COVERAGE * len(universe):
        # Az EKB még nem közölt (vagy hiányos): nem becslünk régebbi napra.
        log.warning("fx_forecast_no_fixing", day=str(day), covered=int(covered))
        return {"session": str(day), "status": "no_fixing"}
    regime = fx_regime(prices, universe)
    macro = _read_table(storage, MACRO_PATH)
    if macro is not None:
        macro = macro.set_index("date")
    features = build_fx_features(prices, universe, regime, macro)
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
    # Devizán nincs volumen és rés: a sokk-jel az F5-ben jön, addig kimondjuk, hogy nincs.
    frame["shock_tracked"] = False
    frame["withheld"] = False
    package = _package_bytes(frame)
    entry = manifest_entry(day, package, frame, now.astimezone(UTC), len(universe), FAMILY, VERSION, CALENDAR)
    if dry_run:
        return {**entry, "status": "dry_run"}
    storage.upload(RAW_BUCKET, package_path(day), package, "application/octet-stream")
    storage.upload(
        RAW_BUCKET,
        f"runs/forecast-fx/{day.isoformat()}.json",
        json.dumps(entry, indent=2).encode(),
        "application/json",
    )
    log.info("fx_forecast_saved", **entry)
    return {**entry, "status": "saved"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze deviza napi becslés")
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
