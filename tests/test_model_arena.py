"""A modell-aréna napi becslése és élő mérése (`docs/modell-arena.md`, 2. fejezet)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from pipeline.forecast.run import build_challenger_forecasts
from pipeline.model.config import MODEL_FAMILY
from pipeline.resolve.arena import models_live


class _Constant:
    """Egy kihívó helyett: rögzített becslés, hogy a párosítást lehessen nézni."""

    version = "v1"

    def __init__(self, prob: float) -> None:
        self.prob = prob

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "instrument_id": frame["instrument_id"].to_numpy(),
                "date": frame["date"].to_numpy(),
                "horizon": 0,
                "expected_return": 0.0,
                "prob_up": self.prob,
                "band_low": -0.1,
                "band_high": 0.1,
            }
        )


def test_a_kihivo_a_fo_csomag_soraihoz_parosul() -> None:
    session = date(2026, 9, 25)
    features = pd.DataFrame(
        {"instrument_id": ["CZ1", "CZ2", "CZ3"], "date": [session] * 3, "history_sessions": [400, 400, 10]}
    )
    main = pd.DataFrame(
        {
            "instrument_id": ["CZ1", "CZ2", "CZ1", "CZ2"],
            "horizon": [5, 5, 20, 20],
            "baseline_prob": [0.55, 0.52, 0.56, 0.51],
            "target_session": [date(2026, 10, 2)] * 2 + [date(2026, 10, 23)] * 2,
            "regime": ["normal"] * 4,
        }
    )
    challengers = {
        "ar-linear": {5: _Constant(0.6), 20: _Constant(0.6)},
        "mlp-core": {5: _Constant(0.4), 20: _Constant(0.4)},
    }
    out = build_challenger_forecasts(
        features, session, challengers, main, datetime(2026, 9, 25, 22, tzinfo=UTC)
    )

    # a rövid múltú CZ3-ra nincs becslés, ugyanúgy, mint a fő modellnél
    assert set(out["instrument_id"]) == {"CZ1", "CZ2"}
    assert len(out) == 2 * 2 * 2  # család × horizont × papír
    # a baseline és a célnap a fő csomagból jön, soronként
    row = out[(out["model_family"] == "ar-linear") & (out["instrument_id"] == "CZ2") & (out["horizon"] == 20)]
    assert float(row["baseline_prob"].iloc[0]) == 0.51
    assert row["target_session"].iloc[0] == date(2026, 10, 23)
    # minden becslésnek saját azonosítója van, családonként is
    assert out["forecast_id"].is_unique


def _outcomes(family: str, version: str, hit_rate: float, rows: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = [date(2026, 1, 1) + timedelta(days=i % 120) for i in range(rows)]
    hit = (rng.random(rows) < hit_rate).astype(float)
    return pd.DataFrame(
        {
            "instrument_id": [f"CZ{i % 40}" for i in range(rows)],
            "session": days,
            "horizon": 5,
            "model_family": family,
            "model_version": version,
            "hit": hit,
            "baseline_hit": (rng.random(rows) < 0.5).astype(float),
            "brier": rng.random(rows) * 0.3,
            "baseline_brier": rng.random(rows) * 0.3,
            "covered": (rng.random(rows) < 0.9).astype(float),
        }
    ).drop_duplicates(["instrument_id", "session", "horizon"])


def test_az_elo_arena_minden_csaladot_ugyanazon_a_mintan_mer() -> None:
    main = _outcomes(MODEL_FAMILY, "v1", 0.5, 6000, 1)
    arena = pd.concat(
        [_outcomes("ar-linear", "v1", 0.5, 3000, 2), _outcomes("mlp-core", "v1", 0.5, 3000, 2)],
        ignore_index=True,
    )
    table = models_live(arena, main)

    families = set(table["family"])
    assert families == {MODEL_FAMILY, "ar-linear", "mlp-core"}
    # az lgbm-core csak a kihívókkal közös sorokon szerepel
    lgbm_n = table[(table["family"] == MODEL_FAMILY) & (table["metric"] == "direction_accuracy")]["n"].iloc[0]
    shared = arena[["instrument_id", "session", "horizon"]].drop_duplicates()
    assert lgbm_n == len(main.merge(shared, on=["instrument_id", "session", "horizon"]))
    # az lgbm-core elleni párosított összevetés csak a kihívóknál van
    against_lgbm = table[table["against"] == MODEL_FAMILY]
    assert set(against_lgbm["family"]) == {"ar-linear", "mlp-core"}
    assert set(against_lgbm["metric"]) == {"direction_accuracy", "brier"}
    # a korrekció az egész aréna-családra ment
    assert (table["n_tests"] == len(table)).all()


def test_ures_arena_ures_tabla() -> None:
    assert models_live(pd.DataFrame(), pd.DataFrame()).empty
