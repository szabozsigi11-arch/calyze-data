"""Labor (`docs/labor.md`): a teljes rács, a költség, a készpénz-időszakok és a korrekció."""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.model.lab import COSTS, THRESHOLDS, UNIVERSES, run_lab


def scored(horizon: int = 5, days: int = 400, seed: int = 2) -> tuple[pd.DataFrame, dict[str, str]]:
    """Becslések, ahol a magas valószínűségű papírok tényleg jobban mennek."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-02", periods=days).date
    segments = {f"CZ{i:03d}": ("sp500" if i < 20 else "midcap" if i < 30 else "etf") for i in range(34)}
    rows = []
    for d in dates:
        for instrument in segments:
            p = rng.uniform(0.35, 0.72)
            y = rng.normal(0.01 * (p - 0.5), 0.02)
            rows.append({"instrument_id": instrument, "date": d, "horizon": horizon, "prob_up": p, "y": y})
    return pd.DataFrame(rows), segments


def test_a_teljes_racs_kiszamolodik() -> None:
    data, segments = scored()
    lab = run_lab(data, segments)
    assert len(lab) == len(UNIVERSES) * len(THRESHOLDS) * len(COSTS)
    # a korrekció az egész rácson ment
    assert (lab["n_tests"] == len(lab)).all()
    assert lab["curve"].map(len).max() <= 120


def test_nem_atfedo_idoszakok() -> None:
    data, segments = scored(horizon=20, days=400)
    lab = run_lab(data, segments)
    assert (lab["periods"] == 20).all()  # 400 nap / 20


def test_a_koltseg_csak_ront() -> None:
    data, segments = scored()
    lab = run_lab(data, segments).set_index(["universe", "horizon", "threshold", "cost"]).sort_index()
    for (universe, _horizon, threshold), part in lab.groupby(level=[0, 1, 2]):
        returns = part["ann_return"].to_numpy()
        assert (np.diff(returns) <= 1e-12).all(), (universe, threshold)


def test_a_buy_and_hold_nem_fugg_a_kuszobtol() -> None:
    data, segments = scored()
    lab = run_lab(data, segments)
    for _, part in lab.groupby(["universe", "horizon"]):
        assert part["bh_ann_return"].nunique() == 1


def test_ha_senki_nem_eri_el_a_kuszobot_keszpenz() -> None:
    data, segments = scored()
    data["prob_up"] = data["prob_up"].clip(upper=0.6)  # 0,65 és 0,70 fölé senki
    lab = run_lab(data, segments)
    high = lab[lab["threshold"] >= 0.65]
    assert (high["cash_periods"] == high["periods"]).all()
    assert (high["avg_positions"] == 0).all()
    assert (high["share_better"] <= 1).all()
