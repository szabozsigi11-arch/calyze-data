"""A labor: a modell becsléseit szabályként követve (`docs/labor.md`).

A bemenet az `lgbm-core` mintán kívüli becslései a purged walk-forward
backtestből. A teljes 144 pontos rács minden pontja kiszámolódik — a gyengék
is —, és a BH-korrekció a teljes rácson fut.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from pipeline.model.evaluate import apply_fdr, compare, observations_needed, verdict

UNIVERSES: tuple[str, ...] = ("all", "sp500", "midcap", "etf")
THRESHOLDS: tuple[float, ...] = (0.55, 0.60, 0.65, 0.70)
COSTS: tuple[float, ...] = (0.0, 0.001, 0.0025)
METRIC = "excess_return"
#: A görbe ennyi pontra ritkítva megy a felületre.
CURVE_POINTS = 120


def _annualised(returns: np.ndarray, horizon: int) -> tuple[float, float]:
    per_year = 252 / horizon
    growth = float(np.prod(1 + returns))
    years = len(returns) / per_year
    ann = growth ** (1 / years) - 1 if years > 0 and growth > 0 else float("nan")
    vol = float(np.std(returns, ddof=1) * np.sqrt(per_year)) if len(returns) > 1 else float("nan")
    return ann, vol


def _max_drawdown(returns: np.ndarray) -> float:
    curve = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(curve)
    return float((curve / peak - 1).min()) if len(curve) else float("nan")


def _curve(dates: list, strategy: np.ndarray, hold: np.ndarray) -> list[list[object]]:
    """A két kumulált görbe ritkítva: [dátum, szabály, buy & hold]."""
    s, b = np.cumprod(1 + strategy), np.cumprod(1 + hold)
    idx = np.unique(np.linspace(0, len(dates) - 1, min(CURVE_POINTS, len(dates))).astype(int))
    return [[str(dates[i]), round(float(s[i]), 4), round(float(b[i]), 4)] for i in idx]


def run_lab(scored: pd.DataFrame, segments: Mapping[str, str]) -> pd.DataFrame:
    """A rács minden pontja: hozamok, visszaesés, verdikt a buy & hold ellen, görbe."""
    if scored.empty:
        return pd.DataFrame()
    data = scored[["instrument_id", "date", "horizon", "prob_up", "y"]].copy()
    data["segment"] = data["instrument_id"].map(segments).fillna("")
    data["ret"] = np.expm1(data["y"].to_numpy(dtype="float64"))

    meta: list[dict[str, object]] = []
    comparisons = []
    for horizon, rows in data.groupby("horizon", sort=True):
        h = int(horizon)
        # Nem átfedő időszakok: minden h-adik nap, amire van becslés.
        dates = sorted(rows["date"].unique())
        rebalance = set(dates[::h])
        at = rows[rows["date"].isin(rebalance)]
        for universe in UNIVERSES:
            sub = at if universe == "all" else at[at["segment"] == universe]
            if sub.empty:
                continue
            hold = sub.groupby("date")["ret"].mean().sort_index()
            days = list(hold.index)
            for threshold in THRESHOLDS:
                chosen = sub[sub["prob_up"] >= threshold]
                gross = chosen.groupby("date")["ret"].mean().reindex(hold.index).fillna(0.0)
                count = chosen.groupby("date").size().reindex(hold.index).fillna(0).astype(int)
                for cost in COSTS:
                    strategy = (gross - cost * (count > 0)).to_numpy(dtype="float64")
                    bh = hold.to_numpy(dtype="float64")
                    c = compare(
                        METRIC, strategy, bh, pd.to_datetime(pd.Series(days)).astype("int64").to_numpy(), h
                    )
                    ann_s, vol_s = _annualised(strategy, h)
                    ann_b, vol_b = _annualised(bh, h)
                    invested = count > 0
                    meta.append(
                        {
                            "universe": universe,
                            "horizon": h,
                            "threshold": threshold,
                            "cost": cost,
                            "periods": len(days),
                            "first": str(days[0]),
                            "last": str(days[-1]),
                            "ann_return": ann_s,
                            "ann_vol": vol_s,
                            "max_drawdown": _max_drawdown(strategy),
                            "bh_ann_return": ann_b,
                            "bh_ann_vol": vol_b,
                            "bh_max_drawdown": _max_drawdown(bh),
                            "share_better": float(np.mean(strategy > bh)),
                            "avg_positions": float(count[invested].mean()) if invested.any() else 0.0,
                            "cash_periods": int((~invested).sum()),
                            "curve": _curve(days, strategy, bh),
                        }
                    )
                    comparisons.append(c)

    apply_fdr(comparisons)
    return pd.DataFrame(
        [
            {
                **m,
                "excess_per_period": c.delta,
                "n_eff": c.n_eff,
                "p_value_fdr": c.p_value_fdr,
                "verdict": verdict(c),
                "observations_needed": observations_needed(c),
                "n_tests": len(comparisons),
            }
            for m, c in zip(meta, comparisons, strict=True)
        ]
    )
