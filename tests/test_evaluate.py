"""A mérési protokoll tesztjei (spec/06, 5–6. és 9. fejezet)."""

from datetime import date, timedelta

import numpy as np
import pytest

from pipeline.model.evaluate import (
    Comparison,
    apply_fdr,
    block_bootstrap,
    compare,
    coverage_verdict,
    observations_needed,
    verdict,
)


def correlated_zero_effect(rng: np.random.Generator, days: int = 500, per_day: int = 40, horizon: int = 20):
    """Nulla valódi különbség, de a megfigyelések erősen összefüggnek.

    Két forrásból: egy napon minden papír ugyanazt a piaci sokkot kapja
    (együttmozgás), és a napi hatás h napon át kitart (átfedő horizont).
    """
    shock = rng.normal(0, 1, days + horizon)
    rolling = np.convolve(shock, np.ones(horizon) / horizon, mode="valid")[:days]
    d, day_index = [], []
    start = date(2020, 1, 1)
    for i in range(days):
        d.append(rolling[i] + rng.normal(0, 0.3, per_day))
        day_index.append([start + timedelta(days=i)] * per_day)
    return np.concatenate(d), np.array([x for row in day_index for x in row])


def test_synthetic_null_is_not_called_significant_more_than_about_five_percent():
    """Spec/06, 5. lépés: korrelált, hatás nélküli adaton legfeljebb kb. 5%."""
    rng = np.random.default_rng(11)
    significant = 0
    runs = 30
    for i in range(runs):
        d, days = correlated_zero_effect(rng)
        _, p, _ = block_bootstrap(d, days, horizon=20, reps=400, seed=i)
        significant += p < 0.05
    assert significant / runs <= 0.15  # 30 futásnál a véletlen ingadozás is belefér


def test_ignoring_the_dependence_would_cry_wolf():
    """Kontroll: ugyanazon az adaton a függetlenséget feltételező próba sokszor téved."""
    rng = np.random.default_rng(12)
    from scipy import stats

    wrong = 0
    runs = 30
    for _ in range(runs):
        d, _ = correlated_zero_effect(rng)
        wrong += stats.ttest_1samp(d, 0).pvalue < 0.05
    assert wrong / runs > 0.3


def test_effective_sample_is_far_below_the_raw_count_when_observations_overlap():
    rng = np.random.default_rng(3)
    d, days = correlated_zero_effect(rng)
    _, _, n_eff = block_bootstrap(d, days, horizon=20, reps=400, seed=1)
    assert n_eff < len(d) / 20


def test_independent_observations_keep_their_sample_size():
    rng = np.random.default_rng(4)
    days = np.array([date(2020, 1, 1) + timedelta(days=i) for i in range(600)])
    d = rng.normal(0, 1, 600)
    _, _, n_eff = block_bootstrap(d, days, horizon=2, reps=400, seed=2)
    assert n_eff > 300  # nagyságrendileg a nyers mintaszám


def comparison(
    delta: float, p: float = 0.001, n: int = 400, n_eff: float = 100, metric: str = "direction_accuracy"
):
    return Comparison(
        metric=metric,
        value=0.55,
        baseline_value=0.55 - delta,
        delta=delta,
        n=n,
        n_eff=n_eff,
        p_value=p,
        p_value_fdr=p,
    )


@pytest.mark.parametrize(
    ("delta", "p", "n", "n_eff", "expected"),
    [
        (0.021, 0.02, 412, 64, "better_significant"),
        (0.021, 0.20, 412, 64, "better_not_significant"),
        (0.002, 0.60, 412, 64, "same"),
        (-0.014, 0.04, 412, 64, "worse"),
        (0.021, 0.001, 12, 12, "too_early"),
        # n_eff < 30: szignifikanciát nem mondunk ki (spec/06, 5. lépés)
        (0.021, 0.001, 412, 20, "better_not_significant"),
    ],
)
def test_the_five_verdict_states(delta, p, n, n_eff, expected):
    assert verdict(comparison(delta, p, n, n_eff)) == expected


def test_same_margin_is_half_a_percentage_point():
    # A sorrend rögzített (CLAUDE.md, 2026-09-19): a szignifikancia előbbre való,
    # mint a gyakorlati küszöb — egy kicsi, de kimutatható előny is előny.
    assert verdict(comparison(0.0049, p=0.001)) == "better_significant"
    assert verdict(comparison(0.0049, p=0.6)) == "same"
    assert verdict(comparison(0.0051, p=0.5)) == "better_not_significant"
    assert verdict(comparison(-0.0051, p=0.5)) == "worse"


def test_lower_is_better_for_brier():
    # Kisebb Brier = jobb, tehát a negatív delta a jó irány.
    assert verdict(comparison(-0.02, p=0.01, metric="brier")) == "better_significant"
    assert verdict(comparison(0.02, p=0.01, metric="brier")) == "worse"


def test_coverage_is_judged_by_closeness_to_the_nominal_level():
    assert coverage_verdict(comparison(0.01, metric="coverage")) == "same"
    assert coverage_verdict(comparison(0.07, metric="coverage")) == "worse"  # túl széles sáv sem jó
    assert coverage_verdict(comparison(-0.07, metric="coverage")) == "worse"


def test_fdr_correction_raises_p_values_when_many_comparisons_are_tested():
    raw = [0.001, 0.02, 0.03, 0.2, 0.5]
    comparisons = [comparison(0.01, p=p) for p in raw]
    apply_fdr(comparisons)
    assert all(c.p_value_fdr >= c.p_value for c in comparisons)
    assert comparisons[2].p_value_fdr > 0.03


def test_power_calculation_asks_for_more_observations_for_smaller_differences():
    big = observations_needed(comparison(0.02, p=0.01, n_eff=100))
    small = observations_needed(comparison(0.002, p=0.9, n_eff=100))
    assert small > big > 0


def test_compare_returns_the_measured_values_and_the_difference():
    days = np.array([date(2026, 1, 1) + timedelta(days=i // 10) for i in range(200)])
    model = np.concatenate([np.ones(120), np.zeros(80)])
    baseline = np.concatenate([np.ones(100), np.zeros(100)])
    c = compare("direction_accuracy", model, baseline, days, horizon=5)
    assert c.value == pytest.approx(0.6)
    assert c.baseline_value == pytest.approx(0.5)
    assert c.delta == pytest.approx(0.1)
    assert c.n == 200
