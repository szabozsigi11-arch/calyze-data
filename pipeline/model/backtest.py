"""Purged walk-forward backtest: a modell és a baseline-család mérése (spec/06).

Ez a futás adja az **első valódi választ** arra, hogy a modell ver-e bármit.
A kimenete arénarekordok sora (spec/06, 8. fejezet), amiből a felület
verdictet, mintaszámot és szignifikanciát mutat.

Fontos: ez **backtest**, nem élő mérés. A kettő soha nem keveredhet — a
rekordokban `live = false`, és a felület ezt külön írja ki.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from pipeline.log import get_logger
from pipeline.model.baselines import BASELINE_IDS, add_sector_return, fit_baselines
from pipeline.model.config import (
    BAND_COVERAGE,
    CALIBRATION_SESSIONS,
    HORIZONS,
    MODEL_FAMILY,
    MODEL_VERSION,
    SEED,
    train_stride,
)
from pipeline.model.dataset import add_targets, feature_columns, trainable
from pipeline.model.evaluate import (
    Comparison,
    apply_fdr,
    brier,
    compare,
    covered,
    hit,
    observations_needed,
    verdict,
)
from pipeline.model.predictor import fit_horizon
from pipeline.model.split import Fold, walk_forward

log = get_logger(__name__)

TEST_SESSIONS = 504
MIN_TRAIN_SESSIONS = 756


def _fold_frames(
    data: pd.DataFrame, fold: Fold, horizon: int, sessions: list
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Tanító, kalibrációs és teszt sorok egy foldhoz, purge-dzsel."""
    index = {d: i for i, d in enumerate(sessions)}
    end_i = index[fold.train_end]
    # Csak az a sor tanít, amelynek a CÍMKÉJE is a purge előtt lezárul.
    label_ends_by = data["date"].map(lambda d: index.get(d, -1)) + horizon
    eligible = data[(label_ends_by <= end_i) & (label_ends_by > 0)]
    calib_dates = sorted(eligible["date"].unique())[-CALIBRATION_SESSIONS:]
    calibration = eligible[eligible["date"].isin(calib_dates)]
    train = eligible[~eligible["date"].isin(calib_dates)]
    # Ritkítás a horizont szerint (lásd `train_stride`): a tanítóhalmaz minden
    # n-edik kereskedési napja. A kalibráció és a teszt teljes marad.
    stride = train_stride(horizon)
    if stride > 1:
        keep = set(sorted(train["date"].unique())[::stride])
        train = train[train["date"].isin(keep)]
    test = data[(data["date"] >= fold.test_start) & (data["date"] <= fold.test_end)]
    return train, calibration, test


def run_backtest(
    features: pd.DataFrame,
    prices: pd.DataFrame,
    actions: pd.DataFrame,
    horizons: tuple[int, ...] = HORIZONS,
    test_sessions: int = TEST_SESSIONS,
    min_train: int = MIN_TRAIN_SESSIONS,
) -> pd.DataFrame:
    """Végigmegy a foldokon, és visszaadja a pontozott becsléseket (modell + baseline-ök)."""
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
                log.warning("fold_skipped", horizon=horizon, fold=i, train=len(train), test=len(test))
                continue

            model = fit_horizon(train, calibration, columns, horizon)
            out = model.predict(test)
            out["y"] = test[f"y_{horizon}"].to_numpy()
            out["regime"] = test["regime"].to_numpy()
            out["fold"] = i

            for baseline_id, baseline in fit_baselines(train, horizon).items():
                b = baseline.predict(test)
                out[f"prob_up__{baseline_id}"] = b["prob_up"].to_numpy()
                out[f"expected__{baseline_id}"] = b["expected_return"].to_numpy()
                out[f"band_low__{baseline_id}"] = b["band_low"].to_numpy()
                out[f"band_high__{baseline_id}"] = b["band_high"].to_numpy()

            scored.append(out)
            log.info(
                "fold_done",
                horizon=horizon,
                fold=i,
                train_rows=len(train),
                test_rows=len(test),
                test_from=str(fold.test_start),
                test_to=str(fold.test_end),
            )

    return pd.concat(scored, ignore_index=True) if scored else pd.DataFrame()


def _meta(horizon, regime: str, baseline_id: str, part: pd.DataFrame, live: bool) -> dict[str, object]:
    return {
        "subject_id": f"{MODEL_FAMILY} {MODEL_VERSION}",
        "model_family": MODEL_FAMILY,
        "model_version": MODEL_VERSION,
        "scope": "universe",
        "horizon": int(horizon),
        "regime": regime,
        "baseline_id": baseline_id,
        "live": live,
        "first_observed": str(part["date"].min()),
        "last_observed": str(part["date"].max()),
        "note": "",
    }


def arena_records(scored: pd.DataFrame, live: bool = False) -> pd.DataFrame:
    """A mért értékek a spec/06 8. fejezetének közös rekordszerkezetében."""
    rows: list[dict[str, object]] = []
    comparisons: list[tuple[dict[str, object], Comparison]] = []

    for horizon in sorted(scored["horizon"].unique()):
        for regime in ["all", *sorted(scored["regime"].dropna().unique())]:
            part = scored[scored["horizon"] == horizon]
            if regime != "all":
                part = part[part["regime"] == regime]
            if len(part) < 2:
                continue
            y = part["y"].to_numpy(dtype="float64")
            days = part["date"].to_numpy()
            model_hit, model_brier = hit(part["prob_up"].to_numpy(), y), brier(part["prob_up"].to_numpy(), y)
            coverage = covered(part["band_low"].to_numpy(), part["band_high"].to_numpy(), y)

            # A sáv-lefedettség önálló metrika (spec/06, 2. fejezet): nem egy
            # baseline ellen mérjük, hanem a névleges 90%-hoz képest.
            cov_comparison = compare(
                "coverage", coverage, np.full(len(coverage), BAND_COVERAGE), days, int(horizon)
            )
            comparisons.append(
                (
                    {
                        **_meta(horizon, regime, "nominal_90", part, live),
                        "note": "a 90%-os névleges lefedettséghez mérve",
                    },
                    cov_comparison,
                )
            )

            for baseline_id in BASELINE_IDS:
                base_prob = part[f"prob_up__{baseline_id}"].to_numpy()
                for metric, model_rows, base_rows in (
                    ("direction_accuracy", model_hit, hit(base_prob, y)),
                    ("brier", model_brier, brier(base_prob, y)),
                ):
                    c = compare(metric, model_rows, base_rows, days, int(horizon))
                    comparisons.append((_meta(horizon, regime, baseline_id, part, live), c))

    apply_fdr([c for _, c in comparisons])
    for meta, c in comparisons:
        # A spec/06 8. fejezete a találatszámot is kéri; aránymetrikánál ez a
        # mért arány és a mintaszám szorzata, Brier-pontszámnál nincs értelme.
        is_rate = c.metric in {"direction_accuracy", "coverage"}
        rows.append(
            {
                **meta,
                **{k: v for k, v in asdict(c).items()},
                "hits": round(c.value * c.n) if is_rate else None,
                "baseline_hits": round(c.baseline_value * c.n) if is_rate else None,
                "n_tests": len(comparisons),
                "verdict": verdict(c),
                "observations_needed": observations_needed(c),
            }
        )
    return pd.DataFrame(rows)


def calibration_table(scored: pd.DataFrame, width: float = 0.05) -> pd.DataFrame:
    """Kalibrációs tábla: „amikor 60–70%-ot mondtunk, hányszor lett igazunk”.

    A pontozott sorok teljes táblája több millió soros, és nincs rá szükség:
    a felület ebből a sávonkénti összesítésből rajzol.
    """
    out = scored.assign(bin=(scored["prob_up"] / width).astype(int) * width)
    grouped = out.groupby(["horizon", "bin"], as_index=False).agg(
        n=("prob_up", "size"),
        said=("prob_up", "mean"),
        happened=("y", lambda v: float((v > 0).mean())),
    )
    return grouped


def daily_table(scored: pd.DataFrame) -> pd.DataFrame:
    """Naponkénti összesítés: a hőtérképhez és a kumulált görbékhez."""
    rows = scored.assign(
        model_hit=hit(scored["prob_up"].to_numpy(), scored["y"].to_numpy()),
        model_brier=brier(scored["prob_up"].to_numpy(), scored["y"].to_numpy()),
        covered=covered(
            scored["band_low"].to_numpy(), scored["band_high"].to_numpy(), scored["y"].to_numpy()
        ),
    )
    for baseline_id in BASELINE_IDS:
        rows[f"hit__{baseline_id}"] = hit(rows[f"prob_up__{baseline_id}"].to_numpy(), rows["y"].to_numpy())
    columns = ["model_hit", "model_brier", "covered", *[f"hit__{b}" for b in BASELINE_IDS]]
    grouped = rows.groupby(["horizon", "date"], as_index=False).agg(
        n=("y", "size"), **{c: (c, "mean") for c in columns}
    )
    return grouped


def summarise(records: pd.DataFrame) -> dict[str, object]:
    """Rövid összefoglaló a legkeményebb baseline ellen, horizontonként."""
    out: dict[str, object] = {
        "model_family": MODEL_FAMILY,
        "model_version": MODEL_VERSION,
        "seed": SEED,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "horizons": {},
    }
    for horizon in sorted(records["horizon"].unique()):
        part = records[(records["horizon"] == horizon) & (records["regime"] == "all")]
        acc = part[part["metric"] == "direction_accuracy"]
        if acc.empty:
            continue
        # A legkeményebb baseline: amelyik ellen a modell a legrosszabbul áll.
        hardest = acc.loc[acc["delta"].idxmin()]
        cov = part[part["metric"] == "coverage"]
        out["horizons"][str(horizon)] = {
            "n": int(hardest["n"]),
            "n_eff": round(float(hardest["n_eff"]), 1),
            "model_accuracy": round(float(hardest["value"]), 4),
            "hardest_baseline": str(hardest["baseline_id"]),
            "baseline_accuracy": round(float(hardest["baseline_value"]), 4),
            "delta_pp": round(float(hardest["delta"]) * 100, 2),
            "p_value_fdr": round(float(hardest["p_value_fdr"]), 4),
            "verdict": str(hardest["verdict"]),
            "band_coverage": round(float(cov["value"].iloc[0]), 4) if not cov.empty else None,
        }
    return out


def to_json(summary: dict[str, object]) -> str:
    return json.dumps(summary, indent=2, default=str)


def library_versions() -> dict[str, str]:
    """A futás metaadatai közé: a determinizmushoz a verziók is kellenek."""
    import lightgbm
    import numpy
    import pandas
    import sklearn

    return {
        "lightgbm": lightgbm.__version__,
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "scikit-learn": sklearn.__version__,
    }
