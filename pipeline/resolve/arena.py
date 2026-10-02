"""A modell-aréna élő mérése (`docs/modell-arena.md`, 2. fejezet).

A kihívók lejárt becsléseit ugyanaz a függvény zárja le, mint a fő modellét
(`resolve_due`), és ugyanazok a metrikák mérik. Két összevetés családonként és
horizontonként:

1. a naiv baseline ellen (irány-találat, Brier) és a névleges 90%-hoz
   (sáv-lefedettség);
2. az `lgbm-core` ellen, **párosítva**: ugyanaz a papír, nap és horizont.

Az `lgbm-core` is szerepel, de csak azokon a sorokon, amelyekhez van kihívó
becslés — így a négy család ugyanazon a mintán áll. A korrekció a teljes
aréna-családon fut.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.config import RAW_BUCKET
from pipeline.features.run import _read_table, _write_table
from pipeline.forecast.run import ARENA_PREFIX
from pipeline.ingest.partitions import from_parquet
from pipeline.ingest.storage import Storage
from pipeline.model.config import MODEL_FAMILY
from pipeline.model.evaluate import apply_fdr, compare, observations_needed, verdict

ARENA_OUTCOMES_PREFIX = "outcomes-arena"
MODELS_LIVE_PATH = "arena/models_live.parquet"
KEY = ["instrument_id", "session", "horizon"]


def arena_outcomes_path(year: int) -> str:
    return f"{ARENA_OUTCOMES_PREFIX}/year={year}.parquet"


def load_arena_forecasts(storage: Storage, years: list[int]) -> pd.DataFrame:
    frames = []
    for year in years:
        for path in storage.list(RAW_BUCKET, f"{ARENA_PREFIX}/{year}"):
            blob = storage.download(RAW_BUCKET, path)
            if blob is not None:
                frames.append(from_parquet(blob))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_arena_outcomes(storage: Storage, years: list[int]) -> pd.DataFrame:
    frames = [f for f in (_read_table(storage, arena_outcomes_path(y)) for y in years) if f is not None]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def write_arena_outcomes(storage: Storage, outcomes: pd.DataFrame) -> None:
    for year in sorted({d.year for d in outcomes["session"]}):
        part = outcomes[[d.year == year for d in outcomes["session"]]].reset_index(drop=True)
        _write_table(storage, arena_outcomes_path(year), part)


def models_live(arena: pd.DataFrame, main: pd.DataFrame) -> pd.DataFrame:
    """A modell-aréna rekordjai: család × horizont × metrika × összevetés."""
    if arena.empty:
        return pd.DataFrame()
    # Az lgbm-core csak a kihívókkal közös sorokon (azonos minta).
    shared = arena[KEY].drop_duplicates()
    lgbm = main.merge(shared, on=KEY, how="inner") if not main.empty else main
    lgbm = lgbm.assign(model_family=MODEL_FAMILY) if not lgbm.empty else lgbm
    subjects = pd.concat([lgbm, arena], ignore_index=True)

    records: list[dict[str, object]] = []
    comparisons = []
    for (family, horizon), part in subjects.groupby(["model_family", "horizon"], sort=True):
        days = part["session"].to_numpy()
        version = str(part["model_version"].iloc[0])
        meta = {
            "family": family,
            "version": version,
            "horizon": int(horizon),
            "first_observed": str(min(part["session"])),
            "last_observed": str(max(part["session"])),
        }
        for metric, model_rows, base_rows, against in (
            ("direction_accuracy", part["hit"].to_numpy(), part["baseline_hit"].to_numpy(), "naive"),
            ("brier", part["brier"].to_numpy(), part["baseline_brier"].to_numpy(), "naive"),
            ("coverage", part["covered"].to_numpy(), np.full(len(part), 0.90), "nominal_90"),
        ):
            comparisons.append(
                ({**meta, "against": against}, compare(metric, model_rows, base_rows, days, int(horizon)))
            )

        if family == MODEL_FAMILY or lgbm.empty:
            continue
        # Párosítva az lgbm-core ellen: csak ahol mindkettő lezárult.
        paired = part.merge(
            lgbm[[*KEY, "hit", "brier"]].rename(columns={"hit": "lgbm_hit", "brier": "lgbm_brier"}),
            on=KEY,
            how="inner",
        )
        if paired.empty:
            continue
        pdays = paired["session"].to_numpy()
        for metric, model_rows, other_rows in (
            ("direction_accuracy", paired["hit"].to_numpy(), paired["lgbm_hit"].to_numpy()),
            ("brier", paired["brier"].to_numpy(), paired["lgbm_brier"].to_numpy()),
        ):
            comparisons.append(
                (
                    {**meta, "against": MODEL_FAMILY},
                    compare(metric, model_rows, other_rows, pdays, int(horizon)),
                )
            )

    apply_fdr([c for _, c in comparisons])
    for meta, c in comparisons:
        records.append(
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
        )
    return pd.DataFrame(records)


def write_models_live(storage: Storage, table: pd.DataFrame) -> None:
    if not table.empty:
        _write_table(storage, MODELS_LIVE_PATH, table)
