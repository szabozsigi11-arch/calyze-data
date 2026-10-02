"""A modell-aréna kihívói (`docs/modell-arena.md`).

Három család az `lgbm-core` mellé: `ar-linear` (statisztikai kontroll),
`mlp-core` (neurális háló) és `ensemble` (a három átlaga). Mindegyik csak egy
pontbecslést ad; az irány-valószínűséget és a sávot ugyanaz a csomagolás
állítja elő, mint az `lgbm-core`-nál (`predictor.py`): conformal sáv a
volatilitással normalizált hibákból, és izotón kalibráció a kalibrációs ablak
két, egymást nem fedő felén. Így a kimenetek csak a pontbecslés módjában
különböznek.

Az `lgbm-core` kódjához ez a fájl nem nyúl: annak az eredményei a v1-es
verzióhoz tartoznak, és nem változhatnak attól, hogy kihívói lettek.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor

from pipeline.model.config import BAND_COVERAGE, SEED
from pipeline.model.predictor import HorizonModel, _ecdf, scale_of

FAMILY_VERSION = "v1"
#: A statisztikai kontroll bemenete: a papír saját hozamai és volatilitása.
AR_INPUTS: tuple[str, ...] = ("ret_1", "ret_5", "ret_20", "ret_60", "vol_20")
AR_ALPHA = 1.0
#: A neurális háló felépítése és a tanító sorok felső határa (a futásidő miatt).
MLP_LAYERS: tuple[int, ...] = (64, 32)
MLP_MAX_ITER = 50
MLP_MAX_ROWS = 300_000


@dataclass
class Standardizer:
    """Hiánypótlás a tanító medián­nal, majd standardizálás a tanító átlagával és szórásával."""

    columns: list[str]
    median: np.ndarray = field(default_factory=lambda: np.zeros(0))
    mean: np.ndarray = field(default_factory=lambda: np.zeros(0))
    std: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def fit(self, frame: pd.DataFrame) -> Standardizer:
        # Másolat: a pandas nézetet is adhat, ami csak olvasható.
        x = frame[self.columns].to_numpy(dtype="float64", copy=True)
        x[~np.isfinite(x)] = np.nan
        self.median = np.nan_to_num(np.nanmedian(x, axis=0))
        filled = np.where(np.isnan(x), self.median, x)
        self.mean = filled.mean(axis=0)
        std = filled.std(axis=0)
        self.std = np.where(std > 0, std, 1.0)
        return self

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        # Másolat: a pandas nézetet is adhat, ami csak olvasható.
        x = frame[self.columns].to_numpy(dtype="float64", copy=True)
        x[~np.isfinite(x)] = np.nan
        filled = np.where(np.isnan(x), self.median, x)
        return (filled - self.mean) / self.std


@dataclass
class ARLinear:
    """Ridge-regresszió a horizont hozamára a papír saját hozamaiból."""

    scaler: Standardizer
    model: Ridge

    @classmethod
    def fit(cls, train: pd.DataFrame, target: str) -> ARLinear:
        scaler = Standardizer(list(AR_INPUTS)).fit(train)
        model = Ridge(alpha=AR_ALPHA).fit(scaler.transform(train), train[target].to_numpy(dtype="float64"))
        return cls(scaler, model)

    def point(self, frame: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.model.predict(self.scaler.transform(frame)), dtype="float64")


@dataclass
class MLPCore:
    """Két rejtett rétegű neurális háló, ugyanazon a feature-táblán, mint az `lgbm-core`."""

    scaler: Standardizer
    model: MLPRegressor
    y_mean: float
    y_std: float

    @classmethod
    def fit(cls, train: pd.DataFrame, target: str, features: Sequence[str]) -> MLPCore:
        if len(train) > MLP_MAX_ROWS:
            train = train.sample(n=MLP_MAX_ROWS, random_state=SEED)
        scaler = Standardizer(list(features)).fit(train)
        y = train[target].to_numpy(dtype="float64")
        # A célváltozót is standardizáljuk: a hozamok kicsik, a háló így tanul stabilan.
        y_mean, y_std = float(y.mean()), float(y.std() or 1.0)
        model = MLPRegressor(
            hidden_layer_sizes=MLP_LAYERS,
            activation="relu",
            solver="adam",
            early_stopping=True,
            validation_fraction=0.1,
            max_iter=MLP_MAX_ITER,
            random_state=SEED,
        ).fit(scaler.transform(train), (y - y_mean) / y_std)
        return cls(scaler, model, y_mean, y_std)

    def point(self, frame: pd.DataFrame) -> np.ndarray:
        z = np.asarray(self.model.predict(self.scaler.transform(frame)), dtype="float64")
        return z * self.y_std + self.y_mean


@dataclass
class Ensemble:
    """A három család pontbecslésének egyenlő súlyú átlaga."""

    lgbm: HorizonModel
    ar: ARLinear
    mlp: MLPCore

    def point(self, frame: pd.DataFrame) -> np.ndarray:
        lgbm_point, _ = self.lgbm.raw(frame)
        return (lgbm_point + self.ar.point(frame) + self.mlp.point(frame)) / 3.0


@dataclass
class FamilyModel:
    """Egy család egy horizontja a közös csomagolással: sáv és kalibrált valószínűség."""

    family: str
    horizon: int
    point_model: ARLinear | MLPCore | Ensemble
    calibrator: IsotonicRegression
    residuals: np.ndarray
    band_q: float
    version: str = FAMILY_VERSION

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        point = self.point_model.point(frame)
        scale = scale_of(frame, self.horizon)
        raw_prob = 1.0 - _ecdf(self.residuals, -point / scale)
        prob = np.clip(self.calibrator.predict(raw_prob), 0.01, 0.99)
        return pd.DataFrame(
            {
                "instrument_id": frame["instrument_id"].to_numpy(),
                "date": frame["date"].to_numpy(),
                "horizon": self.horizon,
                "expected_return": point,
                "prob_up": prob,
                "band_low": point - self.band_q * scale,
                "band_high": point + self.band_q * scale,
            }
        )


def wrap(
    family: str, point_model: ARLinear | MLPCore | Ensemble, calibration: pd.DataFrame, horizon: int
) -> FamilyModel:
    """A közös csomagolás, pontosan az `lgbm-core` módszerével (`predictor.fit_horizon`)."""
    target = f"y_{horizon}"
    half = len(calibration) // 2
    conformal_part, isotonic_part = calibration.iloc[:half], calibration.iloc[half:]

    residuals = (
        conformal_part[target].to_numpy(dtype="float64") - point_model.point(conformal_part)
    ) / scale_of(conformal_part, horizon)
    band_q = float(np.quantile(np.abs(residuals), BAND_COVERAGE))

    point_i = point_model.point(isotonic_part)
    raw_prob = 1.0 - _ecdf(residuals, -point_i / scale_of(isotonic_part, horizon))
    up = (isotonic_part[target].to_numpy(dtype="float64") > 0).astype(float)
    calibrator = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip").fit(raw_prob, up)
    return FamilyModel(family, horizon, point_model, calibrator, residuals, band_q)


def fit_challengers(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
    features: Sequence[str],
    horizon: int,
    lgbm: HorizonModel,
) -> dict[str, FamilyModel]:
    """A három kihívó egy horizontra, ugyanazon a tanító és kalibrációs ablakon, mint az `lgbm`."""
    target = f"y_{horizon}"
    ar = ARLinear.fit(train, target)
    mlp = MLPCore.fit(train, target, features)
    return {
        "ar-linear": wrap("ar-linear", ar, calibration, horizon),
        "mlp-core": wrap("mlp-core", mlp, calibration, horizon),
        "ensemble": wrap("ensemble", Ensemble(lgbm, ar, mlp), calibration, horizon),
    }
