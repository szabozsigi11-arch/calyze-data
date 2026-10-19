import pickle
from pathlib import Path

import pytest

from pipeline.config import RAW_BUCKET
from pipeline.ingest.storage import LocalStorage
from pipeline.model.loading import load_horizon_models


def _save(storage: LocalStorage, horizons: tuple[int, ...]) -> None:
    for h in horizons:
        storage.upload(RAW_BUCKET, f"models/x/h{h}.pkl", pickle.dumps({"h": h}), "application/octet-stream")


def test_missing_extended_horizons_are_skipped_until_the_first_training(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    _save(storage, (5, 20, 60))
    assert sorted(load_horizon_models(storage, "models/x", "train")) == [5, 20, 60]


def test_all_five_horizons_load_once_trained(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    _save(storage, (1, 5, 20, 60, 120))
    assert sorted(load_horizon_models(storage, "models/x", "train")) == [1, 5, 20, 60, 120]


def test_a_missing_core_horizon_still_stops_the_run(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    _save(storage, (1, 5, 60, 120))
    with pytest.raises(RuntimeError, match="20 nap"):
        load_horizon_models(storage, "models/x", "train")
