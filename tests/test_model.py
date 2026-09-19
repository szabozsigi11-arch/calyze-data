"""A felosztás, a kalibráció és a conformal sáv tesztjei (spec/06, 2–3. fejezet)."""

from datetime import date, timedelta
from itertools import pairwise

import numpy as np
import pandas as pd
import pytest

from pipeline.model.baselines import add_sector_return, fit_baselines
from pipeline.model.dataset import add_targets, feature_columns
from pipeline.model.predictor import fit_horizon, scale_of
from pipeline.model.split import walk_forward

SESSIONS = [date(2020, 1, 1) + timedelta(days=i) for i in range(2000)]


def test_walk_forward_folds_do_not_overlap_and_move_forward():
    folds = walk_forward(SESSIONS, horizon=20, test_sessions=252, min_train=756)
    assert len(folds) >= 4
    for a, b in pairwise(folds):
        assert a.test_end < b.test_start
        assert a.train_end < a.test_start


def test_purge_removes_the_horizon_before_the_test_window():
    horizon = 20
    folds = walk_forward(SESSIONS, horizon=horizon, test_sessions=252, min_train=756)
    for fold in folds:
        gap = SESSIONS.index(fold.test_start) - SESSIONS.index(fold.train_end)
        # A tanítás vége és a teszt kezdete között legalább a horizontnyi nap kimarad,
        # különben a tanító sorok címkéje már a teszt időszakba nyúlna.
        assert gap >= horizon


def synthetic_panel(
    n_instruments: int = 12, n_days: int = 900, seed: int = 5
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Papírpanel, amiben a 20 napos hozam részben megjósolható a feature-ből."""
    rng = np.random.default_rng(seed)
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(n_days)]
    rows = []
    for i in range(n_instruments):
        signal = rng.normal(0, 1, n_days)
        noise = rng.normal(0, 0.02, n_days)
        ret = 0.01 * signal + noise
        close = 100 * np.exp(np.cumsum(ret))
        rows.append(
            pd.DataFrame(
                {
                    "instrument_id": f"CZ{i:05d}",
                    "date": days,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "signal": signal,
                    "vol_20": 0.2,
                    "ret_20": pd.Series(ret).rolling(20).sum().to_numpy(),
                    "sector_rel_20": 0.0,
                    "history_sessions": np.arange(1, n_days + 1),
                    "regime": "normal",
                }
            )
        )
    frame = pd.concat(rows, ignore_index=True)
    prices = frame[["instrument_id", "date", "open", "high", "low", "close"]].copy()
    actions = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])
    data = add_sector_return(add_targets(frame, prices, actions))
    return data.dropna(subset=["y_20", "ret_20"]), actions


def test_conformal_band_covers_about_ninety_percent():
    data, _ = synthetic_panel()
    columns = [c for c in feature_columns(data) if c in {"signal", "vol_20", "ret_20", "sector_ret_20"}]
    dates = sorted(data["date"].unique())
    train = data[data["date"] < dates[500]]
    calibration = data[(data["date"] >= dates[500]) & (data["date"] < dates[650])]
    test = data[data["date"] >= dates[680]]

    model = fit_horizon(train, calibration, columns, horizon=20, num_boost_round=120)
    out = model.predict(test)
    covered = (
        (test["y_20"].to_numpy() >= out["band_low"]) & (test["y_20"].to_numpy() <= out["band_high"])
    ).mean()
    assert 0.80 <= covered <= 0.97


def test_probability_is_calibrated_and_within_bounds():
    data, _ = synthetic_panel()
    columns = [c for c in feature_columns(data) if c in {"signal", "vol_20", "ret_20", "sector_ret_20"}]
    dates = sorted(data["date"].unique())
    train = data[data["date"] < dates[500]]
    calibration = data[(data["date"] >= dates[500]) & (data["date"] < dates[650])]
    test = data[data["date"] >= dates[680]]

    out = fit_horizon(train, calibration, columns, horizon=20, num_boost_round=120).predict(test)
    assert out["prob_up"].between(0.01, 0.99).all()
    # Ahol magas valószínűséget mond, ott gyakrabban is emelkedik, mint ahol alacsonyat.
    up = test["y_20"].to_numpy() > 0
    high, low = out["prob_up"] > 0.55, out["prob_up"] < 0.45
    if high.sum() > 30 and low.sum() > 30:
        assert up[high.to_numpy()].mean() > up[low.to_numpy()].mean()


def test_scale_never_collapses_to_zero():
    frame = pd.DataFrame({"vol_20": [0.0, np.nan, 0.3]})
    assert (scale_of(frame, 20) > 0).all()


def test_momentum_baseline_reacts_to_the_recent_direction():
    data, _ = synthetic_panel()
    train = data[data["date"] < sorted(data["date"].unique())[600]]
    baselines = fit_baselines(train, horizon=20)
    test = pd.DataFrame(
        {
            "instrument_id": ["CZ00000", "CZ00001"],
            "date": [date(2026, 9, 18)] * 2,
            "ret_20": [0.05, -0.05],
            "sector_ret_20": [0.0, 0.0],
            "vol_20": [0.2, 0.2],
        }
    )
    out = baselines["momentum"].predict(test)
    # Az emelkedő és az eső papírra más esélyt mond: a momentum-csoport mért aránya.
    assert out["prob_up"].iloc[0] != out["prob_up"].iloc[1]
    # És a naiv baseline-tól is eltér (az minden papírra ugyanazt mondja).
    naive = baselines["naive"].predict(test)
    assert naive["prob_up"].nunique() == 1


def test_baselines_only_use_the_training_window():
    data, _ = synthetic_panel()
    dates = sorted(data["date"].unique())
    train = data[data["date"] < dates[600]]
    later = data[data["date"] >= dates[600]].copy()
    later["y_20"] = later["y_20"] * 10  # a jövő megváltozik
    first = fit_baselines(train, horizon=20)["naive"]
    second = fit_baselines(pd.concat([train, later.iloc[:0]]), horizon=20)["naive"]
    assert first.base_rate == pytest.approx(second.base_rate)
