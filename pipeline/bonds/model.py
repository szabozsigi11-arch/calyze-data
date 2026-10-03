"""A kötvény-modell tanítása és backtestje (`docs/kotveny.md`, 5. fejezet).

Ugyanaz a felépítés, mint a deviza-modell; a modell a hozam `exp(hozam/100)`
„árát” látja, így a célváltozó a hozamváltozás / 100.

Futtatás:
    uv run python -m pipeline.bonds.model --task train
    uv run python -m pipeline.bonds.model --task backtest
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
from pipeline.bonds.calendar import last_bond_day
from pipeline.bonds.features import (
    BONDS_REGIME_PATH,
    EMPTY_ACTIONS,
    as_price,
    bond_regime,
    build_bond_features,
    load_bond_yields,
)
from pipeline.config import RAW_BUCKET, load_settings
from pipeline.features.run import MACRO_PATH, _read_table, _write_table
from pipeline.ingest.bonds import BONDS_HISTORY_START
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.model.backtest import arena_records, library_versions, run_backtest, summarise
from pipeline.model.baselines import fit_baselines
from pipeline.model.config import HORIZONS
from pipeline.model.dataset import add_targets, feature_columns, trainable
from pipeline.model.predictor import fit_horizon
from pipeline.universe import active_on, load_bonds_universe

log = logging_setup.get_logger(__name__)

FAMILY = "lgbm-bonds"
VERSION = "v1"
SCOPE = "bonds"
PARAMS: dict[str, object] = {"min_data_in_leaf": 100}
BASELINES: tuple[str, ...] = ("naive", "momentum")
CALIBRATION_DAYS = 252
TEST_DAYS = 504
MIN_TRAIN_DAYS = 756
MIN_TRAIN_ROWS = 3_000
MIN_CALIBRATION_ROWS = 1_000
MODEL_PREFIX = f"models/{FAMILY}/{VERSION}"
BACKTEST_PATH = "arena/bonds_backtest.parquet"

#: A rezsim ellenőrző időszakai (5. fejezet): csak közöljük, nem hangolunk.
REGIME_CHECKS = (
    ("2008-10-01", "2008-10-31", "stressed"),
    ("2020-03-01", "2020-03-31", "stressed"),
    ("2022-09-01", "2022-09-30", "stressed"),
    ("2017-07-01", "2017-12-31", "calm"),
)


def load_panel(storage: Storage, last: date, today: date) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    yields = load_bond_yields(storage, list(range(BONDS_HISTORY_START.year, last.year + 1)))
    if yields.empty:
        raise RuntimeError("Nincs kötvényhozam a privát tárban — előbb a kötvény-letöltés kell.")
    yields = yields[yields["date"] <= last]
    universe = active_on(load_bonds_universe(), today)
    regime = bond_regime(yields, universe)
    macro = _read_table(storage, MACRO_PATH)
    if macro is not None:
        macro = macro.set_index("date")
    # A célváltozó és a mérés a transzformált „árból” számol (4. fejezet).
    return as_price(yields), build_bond_features(yields, universe, regime, macro), regime


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
    last = last_bond_day(now)
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
    _write_table(storage, BONDS_REGIME_PATH, regime)
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
        f"runs/train-bonds/{last.isoformat()}.json",
        json.dumps(summary, indent=2, default=str).encode(),
        "application/json",
    )
    return summary


def task_backtest(storage: Storage, now: datetime) -> dict[str, object]:
    last = last_bond_day(now)
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
        raise RuntimeError("A kötvény-backtest egyetlen foldot sem tudott lefuttatni.")
    records = arena_records(
        scored, live=False, baseline_ids=BASELINES, family=FAMILY, version=VERSION, scope=SCOPE
    )
    _write_table(storage, BACKTEST_PATH, records)
    summary = {
        **summarise(records),
        "model_family": FAMILY,
        "model_version": VERSION,
        "rows_scored": len(scored),
        "regime_checks": regime_checks(regime),
        "libraries": library_versions(),
    }
    log.info("bonds_backtest_summary", **{k: v for k, v in summary.items() if k != "libraries"})
    storage.upload(
        RAW_BUCKET,
        f"runs/backtest-bonds/{last.isoformat()}.json",
        json.dumps(summary, indent=2, default=str).encode(),
        "application/json",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze kötvény-modell")
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
