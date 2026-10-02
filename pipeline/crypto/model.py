"""A kripto-modell tanítása és backtestje (`docs/kripto-modell.md`, 3–5. fejezet).

Ugyanaz a felépítés, mint a részvényes `pipeline.model.run`: horizontonként
LightGBM + conformal sáv + izotón kalibráció, és a naiv/momentum baseline a
tanító ablakból. A különbség csak a rögzített méretekben van.

Futtatás:
    uv run python -m pipeline.crypto.model --task train
    uv run python -m pipeline.crypto.model --task backtest
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from pipeline import log as logging_setup
from pipeline.calendar import last_closed_session
from pipeline.config import RAW_BUCKET, load_settings
from pipeline.crypto.features import (
    CALENDAR,
    CRYPTO_REGIME_PATH,
    EMPTY_ACTIONS,
    build_crypto_features,
    crypto_regime,
    load_crypto_prices,
)
from pipeline.features.run import MACRO_PATH, _read_table, _write_table
from pipeline.ingest.crypto import CRYPTO_HISTORY_START
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.model.backtest import arena_records, library_versions, run_backtest, summarise
from pipeline.model.baselines import fit_baselines
from pipeline.model.config import HORIZONS
from pipeline.model.dataset import add_targets, feature_columns, trainable
from pipeline.model.predictor import fit_horizon
from pipeline.universe import active_on, load_crypto_universe

log = logging_setup.get_logger(__name__)

FAMILY = "lgbm-crypto"
VERSION = "v1"
SCOPE = "crypto"
#: Az egyetlen eltérés a részvényes beállítástól (3. fejezet).
PARAMS: dict[str, object] = {"min_data_in_leaf": 100}
BASELINES: tuple[str, ...] = ("naive", "momentum")
CALIBRATION_DAYS = 365
TEST_DAYS = 730
MIN_TRAIN_DAYS = 730
MIN_TRAIN_ROWS = 3_000
MIN_CALIBRATION_ROWS = 1_000

MODEL_PREFIX = f"models/{FAMILY}/{VERSION}"
BACKTEST_PATH = "arena/crypto_backtest.parquet"

#: A rezsim ellenőrző időszakai (1. fejezet): csak közöljük, nem hangolunk.
REGIME_CHECKS = (
    ("2020-03-01", "2020-03-31", "stressed"),
    ("2022-05-01", "2022-06-30", "stressed"),
    ("2022-11-01", "2022-11-30", "stressed"),
    ("2023-01-01", "2023-06-30", "calm"),
)


def load_panel(storage: Storage, last: date, today: date) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prices = load_crypto_prices(storage, list(range(CRYPTO_HISTORY_START.year, last.year + 1)))
    if prices.empty:
        raise RuntimeError("Nincs kripto-árfolyam a privát tárban — előbb a kripto-letöltés kell.")
    prices = prices[prices["date"] <= last]
    # A tagság a futás napjára szól (mint a részvényeknél): a ma felvett papír
    # teljes múltja is kell, a `valid_from` nem az adat kezdete.
    universe = active_on(load_crypto_universe(), today)
    regime = crypto_regime(prices, universe)
    macro = _read_table(storage, MACRO_PATH)
    if macro is not None:
        macro = macro.set_index("date")
    return prices, build_crypto_features(prices, universe, regime, macro), regime


def regime_checks(regime: pd.DataFrame) -> list[dict[str, object]]:
    lab = regime.dropna(subset=["regime"]).copy()
    lab["d"] = pd.to_datetime(lab["date"])
    out = []
    for start, end, label in REGIME_CHECKS:
        part = lab[(lab["d"] >= start) & (lab["d"] <= end)]["regime"]
        out.append(
            {"from": start, "to": end, "label": label, "share": round(float((part == label).mean()), 3)}
        )
    return out


def task_train(storage: Storage, now: datetime) -> dict[str, object]:
    last = last_closed_session(now, CALENDAR)
    prices, features, regime = load_panel(storage, last, now.astimezone(UTC).date())
    data = add_targets(features, prices, EMPTY_ACTIONS)
    columns = feature_columns(data)
    trained: dict[str, object] = {}
    for horizon in HORIZONS:
        usable = trainable(data, horizon)
        dates = sorted(usable["date"].unique())
        calib_dates = set(dates[-CALIBRATION_DAYS:])
        train = usable[~usable["date"].isin(calib_dates)]
        calibration = usable[usable["date"].isin(calib_dates)]
        model = fit_horizon(train, calibration, columns, horizon, PARAMS)
        baselines = {k: v for k, v in fit_baselines(train, horizon).items() if k in BASELINES}
        storage.upload(
            RAW_BUCKET,
            f"{MODEL_PREFIX}/h{horizon}.pkl",
            pickle.dumps({"model": model, "baselines": baselines}),
            "application/octet-stream",
        )
        trained[str(horizon)] = {"train_rows": len(train), "calibration_rows": len(calibration)}
    _write_table(storage, CRYPTO_REGIME_PATH, regime)
    summary = {
        "family": FAMILY,
        "version": VERSION,
        "last_day": last.isoformat(),
        "features": len(columns),
        "horizons": trained,
        "regime_checks": regime_checks(regime),
        "libraries": library_versions(),
    }
    storage.upload(
        RAW_BUCKET,
        f"runs/train-crypto/{last.isoformat()}.json",
        json.dumps(summary, indent=2, default=str).encode(),
        "application/json",
    )
    return summary


def task_backtest(storage: Storage, now: datetime) -> dict[str, object]:
    last = last_closed_session(now, CALENDAR)
    prices, features, regime = load_panel(storage, last, now.astimezone(UTC).date())
    scored = run_backtest(
        features,
        prices,
        EMPTY_ACTIONS,
        test_sessions=TEST_DAYS,
        min_train=MIN_TRAIN_DAYS,
        calibration_sessions=CALIBRATION_DAYS,
        min_train_rows=MIN_TRAIN_ROWS,
        min_calibration_rows=MIN_CALIBRATION_ROWS,
        params=PARAMS,
        baseline_ids=BASELINES,
    )
    if scored.empty:
        raise RuntimeError("A kripto-backtest egyetlen foldot sem tudott lefuttatni.")
    records = arena_records(
        scored, live=False, baseline_ids=BASELINES, family=FAMILY, version=VERSION, scope=SCOPE
    )
    _write_table(storage, BACKTEST_PATH, records)
    summary = {
        **summarise(records),
        # A `summarise` a részvényes család nevét írná; itt a kriptóé a mérés alanya.
        "model_family": FAMILY,
        "model_version": VERSION,
        "rows_scored": len(scored),
        "regime_checks": regime_checks(regime),
        "libraries": library_versions(),
    }
    # A publikus naplóba csak az összesített, modellszintű összefoglaló kerül.
    log.info("crypto_backtest_summary", **{k: v for k, v in summary.items() if k != "libraries"})
    storage.upload(
        RAW_BUCKET,
        f"runs/backtest-crypto/{last.isoformat()}.json",
        json.dumps(summary, indent=2, default=str).encode(),
        "application/json",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze kripto-modell")
    parser.add_argument("--task", choices=["train", "backtest"], default="train")
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

    task = task_train if args.task == "train" else task_backtest
    summary = task(storage, datetime.now(UTC))
    print(json.dumps({k: v for k, v in summary.items() if k != "libraries"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
