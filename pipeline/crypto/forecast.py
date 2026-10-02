"""A kripto napi becslése és lenyomata (`docs/kripto-modell.md`, 6. fejezet).

Ugyanaz a commit–reveal, mint a részvényeknél (`pipeline.forecast.run`): a
csomag a privát tárba kerül és soha nem íródik felül; a lenyomata a nyilvános
repóba (`manifests-crypto/`). Az élő rekord az első lenyomatolt naptól számít.

Futtatás:
    uv run python -m pipeline.crypto.forecast --manifest-dir manifests-crypto
    uv run python -m pipeline.crypto.forecast --local data --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import log as logging_setup
from pipeline.calendar import last_closed_session
from pipeline.config import RAW_BUCKET, load_settings
from pipeline.crypto.features import CALENDAR, build_crypto_features, crypto_regime, load_crypto_prices
from pipeline.crypto.model import FAMILY, MODEL_PREFIX, VERSION
from pipeline.features.run import MACRO_PATH, _read_table
from pipeline.forecast.run import MIN_SESSION_COVERAGE, _package_bytes, forecast_id
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.model.config import HORIZONS, MIN_HISTORY_SESSIONS
from pipeline.universe import active_on, load_crypto_universe

log = logging_setup.get_logger(__name__)

PREFIX = "forecasts-crypto"
#: Ennyi naptári év múlt kell a napi feature-ökhöz (EMA-200, 252 napos momentum).
LOOKBACK_YEARS = 3
#: Legfeljebb ennyi nappal korábbi napra becslünk, ha a legutóbbi hiányos.
MAX_LAG_DAYS = 2
#: A nap zárása után ennyi időn belül kell elkészülnie a becslésnek (6. fejezet).
MAX_DELAY = timedelta(hours=6)


def too_late(day: date, now: datetime) -> bool:
    """A nap 24:00 UTC-kor zár; ennél 6 óránál később készült becslés nem számít élőnek."""
    closed = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1)
    return now.astimezone(UTC) - closed > MAX_DELAY


def package_path(day: date) -> str:
    return f"{PREFIX}/{day.year}/{day.isoformat()}.parquet"


def choose_day(coverage: dict[date, int], expected: date, universe_size: int) -> date:
    """A legfrissebb nap, amelyre az univerzum legalább 80%-ának van adata."""
    for lag in range(MAX_LAG_DAYS + 1):
        day = expected - timedelta(days=lag)
        if coverage.get(day, 0) >= MIN_SESSION_COVERAGE * universe_size:
            return day
    raise RuntimeError(f"Nincs elég lefedett kripto-nap {expected} előtt {MAX_LAG_DAYS} napon belül.")


def load_models(storage: Storage) -> dict[int, dict[str, object]]:
    models: dict[int, dict[str, object]] = {}
    for horizon in HORIZONS:
        blob = storage.download(RAW_BUCKET, f"{MODEL_PREFIX}/h{horizon}.pkl")
        if blob is None:
            raise RuntimeError(
                "Nincs betanított kripto-modell — előbb: python -m pipeline.crypto.model --task train"
            )
        models[horizon] = pickle.loads(blob)  # noqa: S301 — saját, privát tárból származó fájl
    return models


def build(
    features: pd.DataFrame, prices: pd.DataFrame, day: date, models: dict, made_at: datetime
) -> pd.DataFrame:
    today = features[(features["date"] == day) & (features["history_sessions"] >= MIN_HISTORY_SESSIONS)]
    if today.empty:
        raise RuntimeError(f"Nincs kripto feature-sor a(z) {day} napra.")
    close = prices[prices["date"] == day].set_index("instrument_id")["close"].astype("float64").to_dict()
    rows = []
    for horizon in HORIZONS:
        bundle = models[horizon]
        model = bundle["model"]
        baselines = bundle["baselines"]
        out = model.predict(today)
        out["contributions"] = [json.dumps(c, separators=(",", ":")) for c in model.contributions(today)]
        out["horizon"] = horizon
        out["baseline_prob"] = baselines["naive"].predict(today)["prob_up"].to_numpy()
        out["baseline_id"] = "naive"
        out["momentum_prob"] = baselines["momentum"].predict(today)["prob_up"].to_numpy()
        out["session"] = day
        # 24/7: a horizont vége naptári nap (tezis-kiertekeles.md, 10.).
        out["target_session"] = day + timedelta(days=horizon)
        out["made_at"] = pd.Timestamp(made_at)
        out["model_family"] = FAMILY
        out["model_version"] = VERSION
        out["calendar"] = CALENDAR
        out["regime"] = today["regime"].to_numpy()
        c = np.array([close.get(i, np.nan) for i in out["instrument_id"]])
        out["close"] = c
        out["price_low"] = c * np.exp(out["band_low"].to_numpy())
        out["price_high"] = c * np.exp(out["band_high"].to_numpy())
        out["expected_price"] = c * np.exp(out["expected_return"].to_numpy())
        # Sokk- és naptári jelölés kriptón az E5-ben jön; addig kimondjuk, hogy nincs.
        out["shock_tracked"] = False
        out["withheld"] = False
        out["forecast_id"] = [forecast_id(i, day, horizon, VERSION) for i in out["instrument_id"]]
        rows.append(out)
    return pd.concat(rows, ignore_index=True).drop(columns=["prob_up_raw"], errors="ignore")


def manifest_entry(day: date, package: bytes, frame: pd.DataFrame, made_at: datetime, universe: int) -> dict:
    return {
        "session": day.isoformat(),
        "calendar": CALENDAR,
        "made_at": made_at.isoformat(timespec="seconds"),
        "model_family": FAMILY,
        "model_version": VERSION,
        "horizons": sorted(int(h) for h in frame["horizon"].unique()),
        "instruments": int(frame["instrument_id"].nunique()),
        "universe": universe,
        "forecasts": len(frame),
        "sha256": hashlib.sha256(package).hexdigest(),
        "bytes": len(package),
        "package": "private storage until the data licence allows publication",
    }


def run(storage: Storage, now: datetime, dry_run: bool = False) -> dict[str, object]:
    expected = last_closed_session(now, CALENDAR)
    universe = active_on(load_crypto_universe(), now.astimezone(UTC).date())
    prices = load_crypto_prices(storage, list(range(expected.year - LOOKBACK_YEARS, expected.year + 1)))
    prices = prices[prices["date"] <= expected]
    regime = crypto_regime(prices, universe)
    macro = _read_table(storage, MACRO_PATH)
    if macro is not None:
        macro = macro.set_index("date")
    features = build_crypto_features(prices, universe, regime, macro)

    coverage = features.groupby("date")["instrument_id"].nunique().to_dict()
    day = choose_day(coverage, expected, len(universe))
    if too_late(day, now):
        # A kimaradt napot nem pótoljuk: kiesett napként látszik.
        log.warning("crypto_forecast_too_late", day=str(day), now=now.isoformat(timespec="minutes"))
        return {"session": str(day), "status": "too_late"}
    if storage.download(RAW_BUCKET, package_path(day)) is not None:
        log.info("crypto_forecast_already_saved", day=str(day))
        return {"session": str(day), "status": "already_saved"}

    frame = build(features, prices, day, load_models(storage), now.astimezone(UTC))
    package = _package_bytes(frame)
    entry = manifest_entry(day, package, frame, now.astimezone(UTC), len(universe))
    if dry_run:
        return {**entry, "status": "dry_run"}
    storage.upload(RAW_BUCKET, package_path(day), package, "application/octet-stream")
    storage.upload(
        RAW_BUCKET,
        f"runs/forecast-crypto/{day.isoformat()}.json",
        json.dumps(entry, indent=2).encode(),
        "application/json",
    )
    log.info("crypto_forecast_saved", **entry)
    return {**entry, "status": "saved"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze kripto napi becslés")
    parser.add_argument("--local", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--manifest-dir", type=Path, help="ide írja a lenyomatot (a nyilvános repóban)")
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
