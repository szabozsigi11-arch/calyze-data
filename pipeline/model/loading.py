"""Horizontonkénti modellek betöltése a privát tárból, minden eszközosztálynak."""

from __future__ import annotations

import pickle

import structlog

from pipeline.config import RAW_BUCKET
from pipeline.ingest.storage import Storage
from pipeline.model.config import CORE_HORIZONS, HORIZONS

log = structlog.get_logger()


def load_horizon_models(storage: Storage, prefix: str, train_hint: str) -> dict[int, object]:
    """A `prefix/h{horizon}.pkl` modellek.

    A régi három időtáv kötelező; a bővített (1 és 120 nap) az első tanításig
    hiányozhat, és addig kimarad. Különben a bevezetés napján a napi futás
    minden eszközosztályon leállna, mielőtt a heti tanítás egyszer lefutott.
    """
    models: dict[int, object] = {}
    for horizon in HORIZONS:
        blob = storage.download(RAW_BUCKET, f"{prefix}/h{horizon}.pkl")
        if blob is None:
            if horizon in CORE_HORIZONS:
                raise RuntimeError(f"Nincs betanított modell: {prefix}, {horizon} nap — előbb: {train_hint}")
            log.warning("model_missing_extended_horizon", prefix=prefix, horizon=horizon)
            continue
        models[horizon] = pickle.loads(blob)  # noqa: S301 — saját, privát tárból származó fájl
    return models
