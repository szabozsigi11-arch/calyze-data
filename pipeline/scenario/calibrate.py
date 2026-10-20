"""Forgatókönyv: becslés „ha az ablakban nem jön váratlan hír” (`docs/forgatokonyv.md`).

A feltételes becslés ugyanabból a modellből jön, mint a napi: a pontbecslés
és a skála változatlan, csak a normalizált hibák eloszlása szűkül azokra a
múltbeli ablakokra, amelyekben **nem szólt a sokk-detektor** (se a papíron, se
a piacon; a definíció rögzített: `docs/sokk-detektor.md`). A naptári esemény
nem számít hírnek.

Így a sáv és az esély ugyanabból az eloszlásból jön, mint a fő becslésnél
(2026-09-19-i döntés), és a „merészebb” sáv pontosan annyival szűkebb,
amennyit a múlt igazol.

A mérés is ugyanígy: foldonként csak a korábbi foldok hírmentes ablakaiból
kalibrálunk, és a következő fold hírmentes ablakain pontozunk, a naiv
baseline ellen. Saját FDR-család (`scope = scenario-<eszközosztály>`).
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from pipeline.model.config import BAND_COVERAGE
from pipeline.model.evaluate import (
    MIN_OBSERVATIONS,
    Comparison,
    apply_fdr,
    compare,
    coverage_verdict,
    observations_needed,
    verdict,
)

#: A kiírt kvantilisek: 0,5%-tól 99,5%-ig fél százalékonként (199 érték).
QUANTILE_LEVELS = np.round(np.linspace(0.005, 0.995, 199), 4)
REGIMES = ("all", "calm", "normal", "stressed")
#: Ennyi hírmentes korábbi ablak kell egy fold kalibrálásához.
MIN_CALIBRATION_ROWS = 300


def calm_windows(scored: pd.DataFrame, flags: pd.DataFrame, market: pd.Series) -> pd.Series:
    """Soronként: hírmentes volt-e a becslés ablaka (a becslés utáni h nap).

    `flags`: papír-napok `flag` oszloppal (a detektor papír-jele); `market`:
    dátum → piaci jel. Az ablak a becslés napja UTÁNI h saját nap (a becslés
    napjának hírét a becslés már látta). Ahol az ablak még nem zárult le, NaN.
    """
    f = flags[["instrument_id", "date", "flag"]].copy()
    # A dátum mindenhol naptári nap (a jelek és a becslések más típusban érkezhetnek).
    f["date"] = pd.to_datetime(f["date"]).dt.date
    on_market = {pd.Timestamp(d).date(): bool(v) for d, v in market.items()}
    f["flag"] = f["flag"].fillna(False).astype(bool) | f["date"].map(on_market).fillna(False).astype(bool)
    f = f.sort_values(["instrument_id", "date"]).reset_index(drop=True)
    f["cs"] = f.groupby("instrument_id")["flag"].cumsum()
    out = pd.Series(np.nan, index=scored.index, dtype="float64")
    for horizon in sorted(scored["horizon"].unique()):
        ahead = f.groupby("instrument_id")["cs"].shift(-int(horizon))
        f_h = f.assign(window=ahead - f["cs"])[["instrument_id", "date", "window"]]
        rows = scored[scored["horizon"] == horizon]
        keys = rows[["instrument_id", "date"]].assign(date=pd.to_datetime(rows["date"]).dt.date)
        merged = keys.merge(f_h, on=["instrument_id", "date"], how="left")
        out.loc[rows.index] = np.where(merged["window"].isna(), np.nan, merged["window"].to_numpy() == 0)
    return out


def normalized_errors(frame: pd.DataFrame) -> np.ndarray:
    return ((frame["y"] - frame["expected_return"]) / frame["scale"]).to_numpy(dtype="float64")


def prob_up(errors: np.ndarray, point: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """P(y > 0) a hírmentes hibák empirikus eloszlásából (mint a fő modell nyers valószínűsége)."""
    ordered = np.sort(errors)
    return 1.0 - np.searchsorted(ordered, -point / scale, side="right") / len(ordered)


def _subset(frame: pd.DataFrame, regime: str) -> pd.DataFrame:
    return frame if regime == "all" else frame[frame["regime"] == regime]


def _record(c: Comparison, meta: Mapping[str, object]) -> dict[str, object]:
    rate = c.metric in {"direction_accuracy", "coverage"}
    return {
        **meta,
        "metric": c.metric,
        "value": round(float(c.value), 4),
        "baseline_value": round(float(c.baseline_value), 4),
        "delta": round(float(c.delta), 4),
        "n": int(c.n),
        "n_eff": round(float(c.n_eff), 1),
        "p_value_fdr": None if np.isnan(c.p_value_fdr) else round(float(c.p_value_fdr), 4),
        "n_tests": int(c.n_tests),
        "verdict": coverage_verdict(c) if c.metric == "coverage" else verdict(c),
        "observations_needed": observations_needed(c) if rate else None,
    }


def measure(scored: pd.DataFrame) -> list[dict[str, object]]:
    """Foldonként előre: a korábbi foldok hírmentes ablakaiból, a következő fold hírmentes ablakain."""
    data = scored[scored["calm"] == 1.0].dropna(subset=["y", "expected_return", "scale"])
    found: list[tuple[dict[str, object], Comparison]] = []
    for horizon in sorted(data["horizon"].unique()):
        at = data[data["horizon"] == horizon]
        for regime in REGIMES:
            part = _subset(at, regime)
            hits, base_hits, covered, days = [], [], [], []
            for fold in sorted(part["fold"].unique()):
                past, test = part[part["fold"] < fold], part[part["fold"] == fold]
                if len(past) < MIN_CALIBRATION_ROWS or test.empty:
                    continue
                errors = normalized_errors(past)
                q = float(np.quantile(np.abs(errors), BAND_COVERAGE))
                point = test["expected_return"].to_numpy(dtype="float64")
                scale = test["scale"].to_numpy(dtype="float64")
                up = test["y"].to_numpy(dtype="float64") > 0
                hits.append((prob_up(errors, point, scale) > 0.5) == up)
                base_hits.append((test["prob_up__naive"].to_numpy(dtype="float64") > 0.5) == up)
                covered.append(np.abs(normalized_errors(test)) <= q)
                days.append(test["date"].to_numpy())
            if not hits:
                continue
            day_arr = np.concatenate(days)
            meta = {"horizon": int(horizon), "regime": regime, "baseline": "naive"}
            found.append(
                (
                    meta,
                    compare(
                        "direction_accuracy",
                        np.concatenate(hits).astype("float64"),
                        np.concatenate(base_hits).astype("float64"),
                        day_arr,
                        int(horizon),
                    ),
                )
            )
            cov = np.concatenate(covered).astype("float64")
            found.append(
                (
                    {**meta, "baseline": "nominal_90"},
                    compare("coverage", cov, np.full(len(cov), BAND_COVERAGE), day_arr, int(horizon)),
                )
            )
    apply_fdr([c for _, c in found if c.metric == "direction_accuracy"])
    return [_record(c, meta) for meta, c in found]


def calibration(scored: pd.DataFrame) -> dict[str, object]:
    """A felület bemenete: horizontonként és piaci állapotonként a hírmentes hibák kvantilisei."""
    resolved = scored.dropna(subset=["calm", "y", "expected_return", "scale"])
    horizons: dict[str, object] = {}
    for horizon in sorted(resolved["horizon"].unique()):
        at = resolved[resolved["horizon"] == horizon]
        regimes: dict[str, object] = {}
        for regime in REGIMES:
            part = _subset(at, regime)
            calm = part[part["calm"] == 1.0]
            entry: dict[str, object] = {
                "windows": len(part),
                "calm_windows": len(calm),
                "calm_share": round(len(calm) / len(part), 4) if len(part) else None,
            }
            # 30 hírmentes ablak alatt nincs eloszlás (2. sarokkő): a felület „Not enough data”.
            if len(calm) >= MIN_OBSERVATIONS:
                errors = normalized_errors(calm)
                entry["quantiles"] = [round(float(v), 4) for v in np.quantile(errors, QUANTILE_LEVELS)]
                entry["band_q"] = round(float(np.quantile(np.abs(errors), BAND_COVERAGE)), 4)
                entry["band_q_all"] = round(
                    float(np.quantile(np.abs(normalized_errors(part)), BAND_COVERAGE)), 4
                )
            regimes[regime] = entry
        horizons[str(int(horizon))] = regimes
    return {"quantile_levels": [float(v) for v in QUANTILE_LEVELS], "horizons": horizons}


def instrument_shares(scored: pd.DataFrame) -> dict[str, list[float | None]]:
    """Papíronként és horizontonként: a lezárt ablakok hányada volt hírmentes."""
    resolved = scored.dropna(subset=["calm"])
    horizons = sorted(int(h) for h in resolved["horizon"].unique())
    table = resolved.groupby(["instrument_id", "horizon"])["calm"].agg(["mean", "size"]).reset_index()
    out: dict[str, list[float | None]] = {}
    for iid, part in table.groupby("instrument_id"):
        by_h = {
            int(r.horizon): (round(float(r.mean), 3) if r.size >= MIN_OBSERVATIONS else None)
            for r in part.itertuples()
        }
        out[str(iid)] = [by_h.get(h) for h in horizons]
    return out
