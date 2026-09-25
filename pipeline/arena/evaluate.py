"""A jelzések kiértékelése — ugyanazzal a protokollal, amivel a modellt mérjük.

Ez a fájl szándékosan nem tartalmaz saját statisztikát: a blokk-bootstrapet,
az effektív mintaszámot, az FDR-korrekciót és a verdict-szabályt a
`pipeline.model.evaluate` adja. Az indikátor-aréna nem kap enyhébb mércét,
mint a saját modellünk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.arena.signals import DIRECTIONS
from pipeline.model.evaluate import Comparison, apply_fdr, compare, verdict

#: A mért horizontok — ugyanazok, mint a modellnél.
HORIZONS: tuple[int, ...] = (5, 20, 60)

METRIC = "direction_accuracy"


def forward_outcomes(prices: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Emelkedett-e az ár `horizon` kereskedési nap múlva.

    A jelzés napjának zárásától a `horizon`-adik nap zárásáig. Ahol a jövő
    még nem létezik, ott nincs sor — nyitott kimenetelt nem értékelünk ki.
    """
    frame = prices.sort_values(["instrument_id", "date"]).reset_index(drop=True)
    close = frame.groupby("instrument_id", sort=False)["close"]
    future = close.shift(-horizon)
    out = frame[["instrument_id", "date"]].copy()
    out["up"] = (future.to_numpy() > frame["close"].to_numpy()).astype("float64")
    out.loc[future.isna().to_numpy(), "up"] = np.nan
    return out.dropna(subset=["up"])


def baseline_direction(outcomes: pd.DataFrame) -> pd.Series:
    """A naiv baseline iránya papíronként: amerre a papír többször ment.

    Ez **kedvez** a baseline-nak: a teljes mérési időszak arányát használja,
    tehát a baseline mintha ismerné a korszak sodródását. Szándékos — így a
    jelzésnek nehezebb nyernie, és ha mégis nyer, az nem a mérés jóindulata.
    """
    return outcomes.groupby("instrument_id")["up"].mean() >= 0.5


def evaluate_rule(
    signals: pd.DataFrame, outcomes: pd.DataFrame, direction: str, horizon: int
) -> Comparison | None:
    """Egy szabály egy horizonton: találati arány a naiv baseline ellen.

    `None`, ha egyetlen jelzésnek sincs lezárt kimenetele.
    """
    joined = signals.merge(outcomes, on=["instrument_id", "date"], how="inner")
    if joined.empty:
        return None

    base_up = baseline_direction(outcomes)
    wants_up = direction == "long"
    rule_hit = (joined["up"] > 0.5) == wants_up
    baseline_hit = (joined["up"] > 0.5) == joined["instrument_id"].map(base_up).astype(bool)

    days = pd.to_datetime(joined["date"]).astype("int64").to_numpy()
    return compare(
        METRIC,
        rule_hit.to_numpy(dtype="float64"),
        baseline_hit.to_numpy(dtype="float64"),
        days,
        horizon,
    )


def arena(signals: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Az egész aréna: minden szabály minden horizonton, FDR-korrekcióval.

    A korrekció a teljes családra megy (szabály × horizont): tizenkét szabály
    három horizonton harminchat összehasonlítás, és ennyiből a puszta véletlen
    is adna „szignifikáns” találatot.
    """
    records: list[dict[str, object]] = []
    comparisons: list[Comparison] = []

    for horizon in HORIZONS:
        outcomes = forward_outcomes(prices, horizon)
        for rule, direction in DIRECTIONS.items():
            rows = signals[signals["rule"] == rule]
            if rows.empty:
                continue
            comparison = evaluate_rule(rows, outcomes, direction, horizon)
            if comparison is None:
                continue
            comparisons.append(comparison)
            records.append({"rule": rule, "direction": direction, "horizon": horizon})

    if not comparisons:
        return pd.DataFrame(
            columns=[
                "rule",
                "direction",
                "horizon",
                "value",
                "baseline_value",
                "delta",
                "n",
                "n_eff",
                "p_value",
                "verdict",
            ]
        )

    apply_fdr(comparisons)
    for record, comparison in zip(records, comparisons, strict=True):
        record.update(
            {
                "value": comparison.value,
                "baseline_value": comparison.baseline_value,
                "delta": comparison.delta,
                "n": comparison.n,
                "n_eff": comparison.n_eff,
                "p_value": comparison.p_value_fdr,
                "verdict": verdict(comparison),
            }
        )
    # Rendezés: a legjobb elöl, de a lista alja ugyanúgy látszik majd.
    return (
        pd.DataFrame(records)
        .sort_values(["horizon", "delta"], ascending=[True, False])
        .reset_index(drop=True)
    )
