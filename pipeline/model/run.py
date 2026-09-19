"""Tanítás és backtest futtatása (spec/05, 5. fejezet; spec/06).

Két feladat:

- `train`: a teljes múltra betanítja a horizontonkénti modelleket, és a
  művészetüket a privát tárba menti. Ebből dolgozik a napi becslés (M3).
  Hetente fut.
- `backtest`: purged walk-forward az egész múltra, és a mérési rekordok
  előállítása (spec/06, 8. fejezet). Ez lassú (órás nagyságrend), ezért
  kézzel vagy havonta indul.

Futtatás:
    uv run python -m pipeline.model.run --task train
    uv run python -m pipeline.model.run --task backtest --local data
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from pipeline import log as logging_setup
from pipeline.calendar import last_closed_session
from pipeline.config import HISTORY_START, RAW_BUCKET, load_settings
from pipeline.features.run import (
    MACRO_PATH,
    REGIME_PATH,
    _load_prices,
    _read_table,
    _write_table,
)
from pipeline.ingest.partitions import ACTIONS_PATH
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.model.backtest import (
    arena_records,
    calibration_table,
    daily_table,
    library_versions,
    random_control,
    run_backtest,
    summarise,
)
from pipeline.model.baselines import add_sector_return, fit_baselines
from pipeline.model.config import CALIBRATION_SESSIONS, HORIZONS, MODEL_FAMILY, MODEL_VERSION, SEED
from pipeline.model.dataset import add_targets, feature_columns, trainable
from pipeline.model.predictor import fit_horizon

log = logging_setup.get_logger(__name__)

ARENA_PATH = "arena/backtest.parquet"
CALIBRATION_PATH = "arena/backtest_calibration.parquet"
DAILY_PATH = "arena/backtest_daily.parquet"
MODEL_PREFIX = f"models/{MODEL_FAMILY}/{MODEL_VERSION}"


def load_panel(storage: Storage, last) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Árfolyam, események és a feature-tábla a privát tárból (a feature-ök újraszámolva)."""
    from pipeline.features.run import build_features
    from pipeline.universe import active_on, load_universe

    years = list(range(HISTORY_START.year, last.year + 1))
    prices = _load_prices(storage, years)
    actions = _read_table(storage, ACTIONS_PATH)
    if actions is None:
        actions = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])
    regime = _read_table(storage, REGIME_PATH)
    macro = _read_table(storage, MACRO_PATH)
    if macro is not None:
        macro = macro.set_index("date")
    universe = active_on(load_universe(), last)
    if regime is None:
        raise RuntimeError("Nincs rezsim-tábla — előbb a feature-futás kell.")
    features = build_features(prices, actions, universe, regime, macro)
    return prices, actions, features


def task_backtest(storage: Storage, now: datetime) -> dict[str, object]:
    last = last_closed_session(now)
    prices, actions, features = load_panel(storage, last)
    scored = run_backtest(features, prices, actions)
    if scored.empty:
        raise RuntimeError("A backtest egyetlen foldot sem tudott lefuttatni.")
    records = arena_records(scored, live=False)
    _write_table(storage, ARENA_PATH, records)
    # A pontozott sorok teljes táblája milliós nagyságrendű (és a tár fájlméret-
    # korlátját is átlépné): csak a két összesítést tároljuk, a felület ezekből dolgozik.
    _write_table(storage, CALIBRATION_PATH, calibration_table(scored))
    _write_table(storage, DAILY_PATH, daily_table(scored))
    summary = {
        **summarise(records),
        "random_control": random_control(scored),
        "libraries": library_versions(),
        "rows_scored": len(scored),
    }
    # A publikus naplóba csak ez az összesített, modellszintű összefoglaló kerül
    # (papíronkénti becslés és árfolyam soha): ez a saját modellünkről szóló
    # mérés, nem a forrás adata.
    log.info("backtest_summary", **{k: v for k, v in summary.items() if k != "libraries"})
    storage.upload(
        RAW_BUCKET,
        f"runs/backtest/{last.isoformat()}.json",
        json.dumps(summary, indent=2, default=str).encode(),
        "application/json",
    )
    return summary


def task_train(storage: Storage, now: datetime) -> dict[str, object]:
    """A végleges modellek a teljes múltra; a kalibrációra az utolsó év marad."""
    last = last_closed_session(now)
    prices, actions, features = load_panel(storage, last)
    data = add_sector_return(add_targets(features, prices, actions))
    columns = feature_columns(data)
    trained: dict[str, object] = {}

    for horizon in HORIZONS:
        usable = trainable(data, horizon)
        dates = sorted(usable["date"].unique())
        calib_dates = set(dates[-CALIBRATION_SESSIONS:])
        train = usable[~usable["date"].isin(calib_dates)]
        calibration = usable[usable["date"].isin(calib_dates)]
        model = fit_horizon(train, calibration, columns, horizon)
        baselines = fit_baselines(train, horizon)

        storage.upload(
            RAW_BUCKET,
            f"{MODEL_PREFIX}/h{horizon}.pkl",
            pickle.dumps({"model": model, "baselines": baselines}),
            "application/octet-stream",
        )
        trained[str(horizon)] = {
            "train_rows": len(train),
            "calibration_rows": len(calibration),
            "band_q": round(model.band_q, 4),
            "train_end": str(train["date"].max()),
        }
        log.info("model_trained", horizon=horizon, rows=len(train))

    meta = {
        "model_family": MODEL_FAMILY,
        "model_version": MODEL_VERSION,
        "seed": SEED,
        "trained_at": now.astimezone(UTC).isoformat(timespec="seconds"),
        "last_session": last.isoformat(),
        "features": columns,
        "libraries": library_versions(),
        "horizons": trained,
    }
    storage.upload(
        RAW_BUCKET, f"{MODEL_PREFIX}/meta.json", json.dumps(meta, indent=2).encode(), "application/json"
    )
    return meta


def task_report(storage: Storage, now: datetime) -> dict[str, object]:
    """A tárolt mérési összesítések kiírása (gyors, nem számol újra).

    Csak összesített, modellszintű számok: a kalibrációs sávok és a
    horizontonkénti verdict. Papíronkénti sor és árfolyam nem kerül bele,
    így a publikus naplóba is kiírható.
    """
    records = _read_table(storage, ARENA_PATH)
    calibration = _read_table(storage, CALIBRATION_PATH)
    if records is None:
        raise RuntimeError("Nincs mérési rekord — előbb a backtest fusson le.")
    stored = storage.download(RAW_BUCKET, f"runs/backtest/{last_closed_session(now).isoformat()}.json")
    report: dict[str, object] = {
        "as_of": now.astimezone(UTC).isoformat(timespec="seconds"),
        **summarise(records),
    }
    if stored is not None:
        report["random_control"] = json.loads(stored).get("random_control")
    if calibration is not None:
        report["calibration"] = [
            {k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}
            for row in calibration.to_dict("records")
        ]
    report["regimes"] = [
        {
            "horizon": int(r.horizon),
            "regime": r.regime,
            "baseline": r.baseline_id,
            "model": round(float(r.value), 4),
            "baseline_value": round(float(r.baseline_value), 4),
            "delta_pp": round(float(r.delta) * 100, 2),
            "n": int(r.n),
            "n_eff": round(float(r.n_eff), 1),
            "p_fdr": round(float(r.p_value_fdr), 4),
            "verdict": r.verdict,
        }
        for r in records[
            (records["metric"] == "direction_accuracy") & (records["regime"] != "all")
        ].itertuples()
    ]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze tanítás és backtest")
    parser.add_argument("--task", choices=["train", "backtest", "report"], required=True)
    parser.add_argument("--local", type=Path, help="helyi mappa a privát tár helyett")
    args = parser.parse_args(argv)

    logging_setup.configure()
    settings = load_settings()
    if args.local:
        storage: Storage = LocalStorage(args.local)
    elif settings.supabase_url and settings.supabase_secret_key:
        storage = SupabaseStorage(settings.supabase_url, settings.supabase_secret_key)
    else:
        log.error("storage_not_configured")
        return 2

    now = datetime.now(UTC)
    tasks = {"backtest": task_backtest, "train": task_train, "report": task_report}
    result = tasks[args.task](storage, now)
    log.info(f"{args.task}_done", **{k: v for k, v in result.items() if k in {"last_session", "rows_scored"}})
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
