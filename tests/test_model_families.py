"""A modell-aréna kihívói (`docs/modell-arena.md`).

Mindhárom család ugyanazt a formát adja, mint az `lgbm-core`; a sáv a
névleges 90% körül fed; a statisztikai kontroll csak a saját bemenetét
látja; az ensemble a három pontbecslés átlaga; és minden determinisztikus.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.model import families
from pipeline.model.dataset import feature_columns
from pipeline.model.families import AR_INPUTS, ARLinear, Ensemble, MLPCore, fit_challengers
from pipeline.model.predictor import fit_horizon
from tests.test_model import synthetic_panel


@pytest.fixture(scope="module")
def panel() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    data, _ = synthetic_panel()
    rng = np.random.default_rng(1)
    # A szintetikus panelben nincs minden AR-bemenet: zajjal pótoljuk.
    for column in ("ret_1", "ret_5", "ret_60"):
        data[column] = rng.normal(0, 0.01, len(data))
    columns = [c for c in feature_columns(data) if c in {"signal", "vol_20", "ret_20", "sector_ret_20"}]
    dates = sorted(data["date"].unique())
    train = data[data["date"] < dates[500]]
    calibration = data[(data["date"] >= dates[500]) & (data["date"] < dates[650])]
    test = data[data["date"] >= dates[680]]
    return train, calibration, test, columns


@pytest.fixture(scope="module")
def fitted(
    panel: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]],
) -> dict[str, families.FamilyModel]:
    train, calibration, _, columns = panel
    lgbm = fit_horizon(train, calibration, columns, horizon=20, num_boost_round=80)
    return fit_challengers(train, calibration, columns, 20, lgbm)


def test_mindharom_csalad_ugyanazt_a_format_adja(panel, fitted) -> None:
    _, _, test, _ = panel
    assert set(fitted) == {"ar-linear", "mlp-core", "ensemble"}
    for name, model in fitted.items():
        out = model.predict(test)
        assert list(out.columns) == [
            "instrument_id",
            "date",
            "horizon",
            "expected_return",
            "prob_up",
            "band_low",
            "band_high",
        ], name
        assert out["prob_up"].between(0.01, 0.99).all(), name
        assert (out["band_low"] <= out["band_high"]).all(), name


def test_a_sav_a_nevleges_90_szazalek_korul_fed(panel, fitted) -> None:
    _, _, test, _ = panel
    y = test["y_20"].to_numpy()
    for name, model in fitted.items():
        out = model.predict(test)
        covered = ((y >= out["band_low"]) & (y <= out["band_high"])).mean()
        assert 0.80 <= covered <= 0.97, (name, covered)


def test_a_statisztikai_kontroll_csak_a_sajat_bemenetet_latja(panel) -> None:
    train, _, test, _ = panel
    model = ARLinear.fit(train, "y_20")
    changed = test.copy()
    changed["signal"] = changed["signal"] * 100  # nem AR-bemenet
    np.testing.assert_allclose(model.point(test), model.point(changed))
    assert set(model.scaler.columns) == set(AR_INPUTS)


def test_az_ensemble_a_harom_atlaga(panel, fitted) -> None:
    _, _, test, _ = panel
    ensemble = fitted["ensemble"].point_model
    assert isinstance(ensemble, Ensemble)
    lgbm_point, _ = ensemble.lgbm.raw(test)
    expected = (lgbm_point + ensemble.ar.point(test) + ensemble.mlp.point(test)) / 3
    np.testing.assert_allclose(ensemble.point(test), expected)


def test_a_neuralis_halo_determinisztikus(panel) -> None:
    train, _, test, columns = panel
    a = MLPCore.fit(train, "y_20", columns).point(test)
    b = MLPCore.fit(train, "y_20", columns).point(test)
    np.testing.assert_array_equal(a, b)


def test_a_neuralis_halo_sorkorlatja(panel, monkeypatch) -> None:
    train, _, _, columns = panel
    monkeypatch.setattr(families, "MLP_MAX_ROWS", 500)
    seen: list[int] = []
    original = families.Standardizer.fit

    def spy(self, frame):  # type: ignore[no-untyped-def]
        seen.append(len(frame))
        return original(self, frame)

    monkeypatch.setattr(families.Standardizer, "fit", spy)
    MLPCore.fit(train, "y_20", columns)
    assert seen == [500]
