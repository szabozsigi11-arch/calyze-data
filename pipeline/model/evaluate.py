"""Mérés: metrikák, szignifikancia, verdict (spec/06, 3–6. és 8. fejezet).

A megfigyelések **nem függetlenek**, két okból: az átfedő horizontok miatt két
egymást követő nap becslése szinte ugyanazt méri, és egy napon a több száz
papír nagy része együtt mozog. Ezért:

- a bootstrap egysége a **kereskedési nap** (az aznapi összes becsléssel
  együtt), és egymást követő napokból álló blokkokat húzunk, a blokkhossz
  legalább a horizont (stationary bootstrap);
- a **hatásos mintaszám** (`n_eff`) abból jön, hogy a bootstrap szerint
  mennyire szór az átlag: `n_eff = Var(d) / Var_boot(átlag)`. Ha a
  megfigyelések függetlenek lennének, ez pont `n`-t adna; minél erősebb a
  függés, annál kevesebbet;
- több összevetésnél **Benjamini–Hochberg FDR-korrekció** kötelező.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from arch.bootstrap import StationaryBootstrap
from statsmodels.stats.multitest import multipletests

from pipeline.model.config import SEED

VerdictState = Literal["better_significant", "better_not_significant", "same", "worse", "too_early"]

#: 30 megfigyelés alatt nincs százalék (2. sarokkő); a szignifikanciához az `n_eff` számít.
MIN_OBSERVATIONS = 30
#: A „Same” határa: arány jellegű metrikánál 0,5 százalékpont (CLAUDE.md, 2026-09-19).
SAME_MARGIN_RATE = 0.005
#: Brier-típusú (0–1 skálájú hibapont) metrikánál.
SAME_MARGIN_SCORE = 0.005
SIGNIFICANCE = 0.05
BOOTSTRAP_REPS = 2000


def hit(prob_up: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Talált-e az irány: 50% felett emelkedést mondunk."""
    return ((prob_up > 0.5) == (y > 0)).astype(float)


def brier(prob_up: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (prob_up - (y > 0).astype(float)) ** 2


def covered(low: np.ndarray, high: np.ndarray, y: np.ndarray) -> np.ndarray:
    return ((y >= low) & (y <= high)).astype(float)


@dataclass
class Comparison:
    """Egy összevetés eredménye: a modell és egy baseline között."""

    metric: str
    value: float
    baseline_value: float
    delta: float
    n: int
    n_eff: float
    p_value: float
    #: FDR-korrekció után (a rangsor családjára); amíg nincs, azonos a nyers p-vel
    p_value_fdr: float = field(default=float("nan"))

    @property
    def higher_is_better(self) -> bool:
        return self.metric not in {"brier", "rmse"}


def block_bootstrap(
    per_row: np.ndarray, days: np.ndarray, horizon: int, reps: int = BOOTSTRAP_REPS, seed: int = SEED
) -> tuple[float, float, float]:
    """Napi blokk-bootstrap egy megfigyelésenkénti különbség-sorozatra.

    Returns:
        (átlag, kétoldali p-érték, hatásos mintaszám)
    """
    frame = pd.DataFrame({"d": per_row, "day": days})
    daily = frame.groupby("day")["d"].agg(["sum", "count"]).sort_index()
    mean = float(daily["sum"].sum() / daily["count"].sum())
    if len(daily) < 3:
        return mean, float("nan"), float(len(per_row))

    block = max(2, min(horizon, len(daily) // 2))
    boot = StationaryBootstrap(block, daily.to_numpy(), seed=np.random.default_rng(seed))
    means = boot.apply(lambda a: np.array([a[:, 0].sum() / a[:, 1].sum()]), reps).ravel()

    # Kétoldali p-érték: a bootstrap-eloszlást a nullára tolva mennyire szélső a mért átlag.
    centred = means - mean
    p = 2 * min(float(np.mean(centred <= -abs(mean))), float(np.mean(centred >= abs(mean))))
    p = min(1.0, max(p, 1 / reps))

    var_boot = float(np.var(means, ddof=1))
    var_obs = float(np.var(per_row, ddof=1))
    n_eff = var_obs / var_boot if var_boot > 0 else float(len(per_row))
    return mean, p, float(min(max(n_eff, 1.0), len(per_row)))


def compare(
    metric: str,
    model_rows: np.ndarray,
    baseline_rows: np.ndarray,
    days: np.ndarray,
    horizon: int,
    seed: int = SEED,
) -> Comparison:
    delta, p, n_eff = block_bootstrap(model_rows - baseline_rows, days, horizon, seed=seed)
    return Comparison(
        metric=metric,
        value=float(np.mean(model_rows)),
        baseline_value=float(np.mean(baseline_rows)),
        delta=delta,
        n=len(model_rows),
        n_eff=n_eff,
        p_value=p,
        p_value_fdr=p,
    )


def apply_fdr(comparisons: list[Comparison], alpha: float = SIGNIFICANCE) -> list[Comparison]:
    """Benjamini–Hochberg korrekció egy nézetben együtt rangsorolt összevetésekre."""
    usable = [c for c in comparisons if np.isfinite(c.p_value)]
    if not usable:
        return comparisons
    _, corrected, _, _ = multipletests([c.p_value for c in usable], alpha=alpha, method="fdr_bh")
    for c, value in zip(usable, corrected, strict=True):
        c.p_value_fdr = float(value)
    return comparisons


#: A lefedettség akkor rendben, ha a névlegestől legfeljebb ennyivel tér el.
COVERAGE_TOLERANCE = 0.02


def coverage_verdict(comparison: Comparison, tolerance: float = COVERAGE_TOLERANCE) -> VerdictState:
    """A sáv-lefedettség önálló metrika: a 90%-hoz való közelség a jó.

    Se nem „jobb”, se nem „rosszabb” a több: ha a sáv 97%-ot fed le, az nem
    pontosabb, hanem szélesebb a kelleténél.
    """
    if comparison.n < MIN_OBSERVATIONS:
        return "too_early"
    return "same" if abs(comparison.delta) <= tolerance else "worse"


def verdict(comparison: Comparison, margin: float | None = None) -> VerdictState:
    """Az öt állapot egyike (spec/06, 6. fejezet; a küszöb a CLAUDE.md-ben).

    A sorrend számít: a mintaszám mindent felülír, utána a szignifikancia, és
    csak azután a gyakorlati küszöb.
    """
    if comparison.metric == "coverage":
        return coverage_verdict(comparison)
    if comparison.n < MIN_OBSERVATIONS:
        return "too_early"
    if margin is None:
        margin = SAME_MARGIN_SCORE if comparison.metric in {"brier", "rmse"} else SAME_MARGIN_RATE
    # A „jobb” iránya metrikafüggő: a Brier-pontszámnál és az RMSE-nél a kisebb a jobb.
    better_by = comparison.delta if comparison.higher_is_better else -comparison.delta

    significant = (
        np.isfinite(comparison.p_value_fdr)
        and comparison.p_value_fdr < SIGNIFICANCE
        and comparison.n_eff >= MIN_OBSERVATIONS
    )
    if better_by > 0 and significant:
        return "better_significant"
    if abs(better_by) < margin:
        return "same"
    if better_by >= margin:
        return "better_not_significant"
    return "worse"


def observations_needed(comparison: Comparison, power: float = 0.8) -> int:
    """Hány (hatásos) megfigyelés kellene, hogy ekkora különbség kimutatható legyen.

    Kétoldali próba 5%-os szinten, 80%-os erővel; a szórást a mért adatból
    vesszük. Ez adja az üres állapot mondatát: „340 observations needed”.
    """
    if comparison.delta == 0 or not np.isfinite(comparison.n_eff) or comparison.n_eff < 2:
        return 0
    # A mért átlag szórása a hatásos mintaszámból: se = |delta| / z_obs.
    se = abs(comparison.delta) / max(_z_from_p(comparison.p_value), 1e-6)
    sd = se * np.sqrt(comparison.n_eff)
    z_alpha, z_beta = 1.959963985, 0.841621234 if power == 0.8 else 1.281551566
    needed = ((z_alpha + z_beta) * sd / abs(comparison.delta)) ** 2
    return int(np.ceil(needed))


def _z_from_p(p: float) -> float:
    """A kétoldali p-értékhez tartozó z-érték (normális közelítés)."""
    from scipy.stats import norm

    if not np.isfinite(p) or p <= 0:
        return 8.0
    return float(abs(norm.ppf(p / 2)))
