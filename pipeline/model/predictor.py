"""A modell két kimenete horizontonként (spec/06, 2. fejezet).

1. **Irány-valószínűség** — kalibrált, nem nyers modell-kimenet.
2. **90%-os predikciós sáv** — split conformal, normalizált hibákból.

Mindkettő ugyanabból a hibaeloszlásból származik, ezért nem mondhatnak
ellent egymásnak (nem fordulhat elő 70%-os emelkedési valószínűség olyan sáv
mellett, amely szinte teljesen a nulla alatt van).

A hibát a t napon ismert volatilitással normalizáljuk (`vol_20`, a horizont
hosszára skálázva): egy nyugodt és egy viharos papír hibája nem azonos
nagyságú, és a sávnak ezt követnie kell.

A conformal sávhoz és a kalibrációhoz a tanító ablak UTÁNI, de a teszt ELŐTTI
napok kellenek; ezt a hívó adja át (`calibration`), és két, egymást nem fedő
félre osztjuk: az egyikből lesz a sáv kvantilise és a nyers valószínűség
eloszlása, a másikból az izotón kalibráció.
"""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from pipeline.model.config import BAND_COVERAGE, LGBM_PARAMS, NUM_BOOST_ROUND
from pipeline.model.dataset import matrix

#: A hiba normalizálásához a legkisebb elfogadott szórás (nulla helyett).
MIN_SCALE = 1e-4


def scale_of(frame: pd.DataFrame, horizon: int) -> np.ndarray:
    """A t napon ismert volatilitásból a horizont hosszára skálázott szórás."""
    vol = frame["vol_20"].to_numpy(dtype="float64")
    scale = np.sqrt(horizon / 252.0) * vol
    return np.where(np.isfinite(scale) & (scale > MIN_SCALE), scale, MIN_SCALE)


@dataclass
class HorizonModel:
    """Egy horizont betanított modellje, a kalibrációval és a sáv kvantilisével együtt."""

    horizon: int
    features: list[str]
    booster: lgb.Booster
    calibrator: IsotonicRegression
    #: a normalizált hibák eloszlása (a sávhoz és a nyers valószínűséghez)
    residuals: np.ndarray
    band_q: float

    def raw(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        point = self.booster.predict(matrix(frame, self.features))
        return np.asarray(point, dtype="float64"), scale_of(frame, self.horizon)

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        point, scale = self.raw(frame)
        # P(y > 0) a normalizált hibák empirikus eloszlásából.
        raw_prob = 1.0 - _ecdf(self.residuals, -point / scale)
        prob = np.clip(self.calibrator.predict(raw_prob), 0.01, 0.99)
        return pd.DataFrame(
            {
                "instrument_id": frame["instrument_id"].to_numpy(),
                "date": frame["date"].to_numpy(),
                "horizon": self.horizon,
                "expected_return": point,
                "prob_up": prob,
                "prob_up_raw": raw_prob,
                "band_low": point - self.band_q * scale,
                "band_high": point + self.band_q * scale,
            }
        )

    def contributions(self, frame: pd.DataFrame, top: int = 6) -> list[list[dict[str, float | str]]]:
        """Soronként a becslést leginkább mozgató feature-ök, előjellel.

        A LightGBM `pred_contrib` kimenete SHAP-érték: az egyes feature-ök
        hozzájárulása a modell kimenetéhez, plusz egy alapérték az utolsó
        oszlopban. Ez a modell működését írja le, nem a piac okságát — a
        felületnek ezt ki is kell mondania (spec/03, 2.1, 6. pont).
        """
        raw = np.asarray(
            self.booster.predict(matrix(frame, self.features), pred_contrib=True), dtype="float64"
        )
        values = raw[:, :-1]
        out: list[list[dict[str, float | str]]] = []
        for row in values:
            order = np.argsort(np.abs(row))[::-1][:top]
            out.append(
                [
                    {"feature": self.features[i], "value": round(float(row[i]), 6)}
                    for i in order
                    if row[i] != 0.0
                ]
            )
        return out


def _ecdf(sample: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Empirikus eloszlásfüggvény: a minta hányad része esik x alá."""
    ordered = np.sort(sample)
    return np.searchsorted(ordered, x, side="right") / len(ordered)


def fit_horizon(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
    features: list[str],
    horizon: int,
    params: dict[str, object] | None = None,
    num_boost_round: int = NUM_BOOST_ROUND,
) -> HorizonModel:
    """Betanít egy horizontot: LightGBM + conformal sáv + izotón kalibráció."""
    target = f"y_{horizon}"
    dataset = lgb.Dataset(matrix(train, features), label=train[target].to_numpy(dtype="float64"))
    booster = lgb.train({**LGBM_PARAMS, **(params or {})}, dataset, num_boost_round=num_boost_round)

    # A kalibrációs ablak két, egymást nem fedő fele: conformal | izotón.
    half = len(calibration) // 2
    conformal_part, isotonic_part = calibration.iloc[:half], calibration.iloc[half:]

    point_c = np.asarray(booster.predict(matrix(conformal_part, features)), dtype="float64")
    scale_c = scale_of(conformal_part, horizon)
    residuals = (conformal_part[target].to_numpy(dtype="float64") - point_c) / scale_c
    band_q = float(np.quantile(np.abs(residuals), BAND_COVERAGE))

    point_i = np.asarray(booster.predict(matrix(isotonic_part, features)), dtype="float64")
    scale_i = scale_of(isotonic_part, horizon)
    raw_prob = 1.0 - _ecdf(residuals, -point_i / scale_i)
    up = (isotonic_part[target].to_numpy(dtype="float64") > 0).astype(float)
    calibrator = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip").fit(raw_prob, up)

    return HorizonModel(
        horizon=horizon,
        features=features,
        booster=booster,
        calibrator=calibrator,
        residuals=residuals,
        band_q=band_q,
    )
