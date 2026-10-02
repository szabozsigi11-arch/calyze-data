"""A modell-aréna backtestje (`docs/modell-arena.md`, 3. fejezet).

Ugyanaz a purged walk-forward, mint az `lgbm-core` backtestjénél
(`backtest.py`): minden foldban mind a négy család ugyanazon a tanító és
kalibrációs ablakon tanul, és ugyanazon a teszt-időszakon mérődik — így az
összevetés páros. Az eredmény **backtest**: a felületen mindig külön, jelölve,
és soha nem keveredik az élő számmal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.log import get_logger
from pipeline.model.backtest import MIN_TRAIN_SESSIONS, TEST_SESSIONS, _fold_frames
from pipeline.model.baselines import add_sector_return, fit_baselines
from pipeline.model.config import HORIZONS, MODEL_FAMILY, MODEL_VERSION
from pipeline.model.dataset import add_targets, feature_columns, trainable
from pipeline.model.evaluate import apply_fdr, brier, compare, covered, hit, observations_needed, verdict
from pipeline.model.families import FAMILY_VERSION, fit_challengers
from pipeline.model.predictor import fit_horizon
from pipeline.model.split import walk_forward

log = get_logger(__name__)


def run_arena_backtest(
    features: pd.DataFrame,
    prices: pd.DataFrame,
    actions: pd.DataFrame,
    horizons: tuple[int, ...] = HORIZONS,
    test_sessions: int = TEST_SESSIONS,
    min_train: int = MIN_TRAIN_SESSIONS,
    num_boost_round: int | None = None,
) -> pd.DataFrame:
    """Pontozott teszt-sorok: papír, nap, horizont, család, valószínűség, sáv, valós hozam, naiv baseline."""
    data = add_sector_return(add_targets(features, prices, actions))
    columns = feature_columns(data)
    sessions = sorted(data["date"].unique())
    scored: list[pd.DataFrame] = []

    for horizon in horizons:
        usable = trainable(data, horizon)
        folds = walk_forward(sessions, horizon, test_sessions=test_sessions, min_train=min_train)
        for i, fold in enumerate(folds, start=1):
            train, calibration, test = _fold_frames(usable, fold, horizon, sessions)
            if len(train) < 10_000 or len(calibration) < 1_000 or test.empty:
                log.warning("arena_fold_skipped", horizon=horizon, fold=i)
                continue
            kwargs = {} if num_boost_round is None else {"num_boost_round": num_boost_round}
            lgbm = fit_horizon(train, calibration, columns, horizon, **kwargs)
            models = {MODEL_FAMILY: lgbm, **fit_challengers(train, calibration, columns, horizon, lgbm)}
            naive = fit_baselines(train, horizon)["naive"].predict(test)["prob_up"].to_numpy()
            y = test[f"y_{horizon}"].to_numpy()
            for family, model in models.items():
                out = model.predict(test)[["instrument_id", "date", "prob_up", "band_low", "band_high"]]
                out = out.assign(
                    horizon=horizon,
                    family=family,
                    version=MODEL_VERSION if family == MODEL_FAMILY else FAMILY_VERSION,
                    y=y,
                    baseline_prob=naive,
                    fold=i,
                )
                scored.append(out)
            log.info("arena_fold_done", horizon=horizon, fold=i, test_rows=len(test))
    return pd.concat(scored, ignore_index=True) if scored else pd.DataFrame()


def arena_backtest_records(scored: pd.DataFrame) -> pd.DataFrame:
    """Ugyanaz a rekordszerkezet, mint az élő modell-arénáé (`resolve/arena.py`), `live = false`-szal."""
    if scored.empty:
        return pd.DataFrame()
    key = ["instrument_id", "date", "horizon"]
    frame = scored.copy()
    prob, base, y = (frame[c].to_numpy(dtype="float64") for c in ("prob_up", "baseline_prob", "y"))
    frame["hit"] = hit(prob, y)
    frame["baseline_hit"] = hit(base, y)
    frame["brier"] = brier(prob, y)
    frame["baseline_brier"] = brier(base, y)
    frame["covered"] = covered(frame["band_low"].to_numpy(), frame["band_high"].to_numpy(), y)
    lgbm = frame[frame["family"] == MODEL_FAMILY][[*key, "hit", "brier"]].rename(
        columns={"hit": "lgbm_hit", "brier": "lgbm_brier"}
    )

    comparisons = []
    for (family, horizon), part in frame.groupby(["family", "horizon"], sort=True):
        days = part["date"].to_numpy()
        meta = {
            "family": family,
            "version": str(part["version"].iloc[0]),
            "horizon": int(horizon),
            "first_observed": str(part["date"].min()),
            "last_observed": str(part["date"].max()),
            "live": False,
        }
        for metric, rows, other, against in (
            ("direction_accuracy", part["hit"], part["baseline_hit"], "naive"),
            ("brier", part["brier"], part["baseline_brier"], "naive"),
            ("coverage", part["covered"], pd.Series(np.full(len(part), 0.90)), "nominal_90"),
        ):
            comparisons.append(
                (
                    {**meta, "against": against},
                    compare(metric, rows.to_numpy(), other.to_numpy(), days, int(horizon)),
                )
            )
        if family == MODEL_FAMILY:
            continue
        paired = part.merge(lgbm, on=key, how="inner")
        pdays = paired["date"].to_numpy()
        for metric, rows, other in (
            ("direction_accuracy", paired["hit"], paired["lgbm_hit"]),
            ("brier", paired["brier"], paired["lgbm_brier"]),
        ):
            comparisons.append(
                (
                    {**meta, "against": MODEL_FAMILY},
                    compare(metric, rows.to_numpy(), other.to_numpy(), pdays, int(horizon)),
                )
            )

    apply_fdr([c for _, c in comparisons])
    return pd.DataFrame(
        [
            {
                **meta,
                "metric": c.metric,
                "value": c.value,
                "baseline_value": c.baseline_value,
                "delta": c.delta,
                "n": c.n,
                "n_eff": c.n_eff,
                "p_value": c.p_value,
                "p_value_fdr": c.p_value_fdr,
                "n_tests": len(comparisons),
                "verdict": verdict(c),
                "observations_needed": observations_needed(c),
            }
            for meta, c in comparisons
        ]
    )
