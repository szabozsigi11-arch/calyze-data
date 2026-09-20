"""A napi becslés és a kiértékelés tesztjei (spec/06, 1. és 3. lépés)."""

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from pipeline.calendar import sessions
from pipeline.forecast.run import build_forecasts, forecast_id, package_path, target_session
from pipeline.resolve.run import live_arena, resolve_due

SESSIONS = sessions(date(2026, 1, 2), date(2026, 9, 18))
TODAY = SESSIONS[-1]


class FakeModel:
    """A tanított modell helyett: rögzített kimenet, hogy a teszt a köré épülő logikát mérje."""

    def __init__(self, prob: float, point: float, band: float):
        self.prob, self.point, self.band = prob, point, band

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        n = len(frame)
        return pd.DataFrame(
            {
                "instrument_id": frame["instrument_id"].to_numpy(),
                "date": frame["date"].to_numpy(),
                "horizon": 0,
                "expected_return": np.full(n, self.point),
                "prob_up": np.full(n, self.prob),
                "band_low": np.full(n, -self.band),
                "band_high": np.full(n, self.band),
            }
        )


def panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for i, instrument in enumerate(["CZ00001", "CZ00002"]):
        close = 100 * np.exp(np.cumsum(np.full(len(SESSIONS), 0.001 * (i + 1))))
        rows.append(
            pd.DataFrame(
                {
                    "instrument_id": instrument,
                    "date": SESSIONS,
                    "close": close,
                    "history_sessions": np.arange(1, len(SESSIONS) + 1) + 400,
                    "regime": "normal",
                    "vol_20": 0.2,
                }
            )
        )
    frame = pd.concat(rows, ignore_index=True)
    return frame, frame[["instrument_id", "date", "close"]].copy()


def test_forecast_id_is_deterministic_and_unique_per_slice():
    a = forecast_id("CZ00001", TODAY, 20, "v1")
    assert a == forecast_id("CZ00001", TODAY, 20, "v1")
    assert a != forecast_id("CZ00001", TODAY, 5, "v1")
    assert a != forecast_id("CZ00002", TODAY, 20, "v1")
    assert a != forecast_id("CZ00001", TODAY, 20, "v2")


def test_target_session_counts_trading_days_not_calendar_days():
    start = SESSIONS[-30]
    assert target_session(start, 20, SESSIONS) == SESSIONS[-10]
    # A horizont vége túlnyúlik a naptáron: nincs célnap.
    assert target_session(SESSIONS[-2], 20, SESSIONS) is None


def test_build_forecasts_writes_a_row_per_instrument_and_horizon():
    features, prices = panel()
    models = {5: FakeModel(0.6, 0.01, 0.08), 20: FakeModel(0.55, 0.02, 0.12), 60: FakeModel(0.5, 0.0, 0.2)}
    bundles = {h: {"model": m, "baselines": {"naive": FakeModel(0.58, 0.01, 0.1)}} for h, m in models.items()}
    out = build_forecasts(features, prices, TODAY, bundles, SESSIONS, datetime(2026, 9, 19, tzinfo=UTC))
    assert len(out) == 2 * 3
    assert set(out["horizon"]) == {5, 20, 60}
    # A sáv árban a záróárra vetítve jelenik meg.
    row = out[(out["horizon"] == 20) & (out["instrument_id"] == "CZ00001")].iloc[0]
    assert row["price_high"] == pytest.approx(row["close"] * np.exp(row["band_high"]))
    assert row["price_low"] < row["close"] < row["price_high"]


def test_package_path_is_partitioned_by_year():
    assert package_path(date(2026, 9, 18)) == "forecasts/2026/2026-09-18.parquet"


def forecasts_for_resolve() -> pd.DataFrame:
    made = SESSIONS[-25]
    target = SESSIONS[-5]
    return pd.DataFrame(
        {
            "forecast_id": ["f1", "f2"],
            "instrument_id": ["CZ00001", "GONE"],
            "session": [made, made],
            "target_session": [target, target],
            "horizon": [20, 20],
            "regime": ["normal", "normal"],
            "model_family": ["lgbm-core", "lgbm-core"],
            "model_version": ["v1", "v1"],
            "prob_up": [0.6, 0.6],
            "baseline_prob": [0.55, 0.55],
            "band_low": [-0.1, -0.1],
            "band_high": [0.1, 0.1],
        }
    )


def prices_for_resolve() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for instrument, until in (("CZ00001", len(SESSIONS)), ("GONE", len(SESSIONS) - 12)):
        days = SESSIONS[:until]
        rows.append(
            pd.DataFrame(
                {
                    "instrument_id": instrument,
                    "date": days,
                    "close": 100 * np.exp(np.cumsum(np.full(len(days), 0.002))),
                }
            )
        )
    actions = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])
    return pd.concat(rows, ignore_index=True), actions


def test_resolution_uses_total_return_and_marks_delisted():
    prices, actions = prices_for_resolve()
    out = resolve_due(
        forecasts_for_resolve(), prices, actions, SESSIONS[-1], datetime(2026, 9, 19, tzinfo=UTC)
    )
    assert set(out["forecast_id"]) == {"f1", "f2"}
    normal = out[out["forecast_id"] == "f1"].iloc[0]
    gone = out[out["forecast_id"] == "f2"].iloc[0]
    assert normal["resolution_type"] == "normal"
    # A kivezetett papír az utolsó ismert napjával zárul, és nem tűnik el a mérésből.
    assert gone["resolution_type"] == "delisted_or_halted"
    assert normal["actual_return"] > 0
    assert normal["hit"] == 1.0  # emelkedést mondtunk, emelkedett


def test_open_forecasts_are_not_resolved_early():
    forecasts = forecasts_for_resolve()
    forecasts["target_session"] = SESSIONS[-1]
    prices, actions = prices_for_resolve()
    out = resolve_due(forecasts, prices, actions, SESSIONS[-3], datetime(2026, 9, 19, tzinfo=UTC))
    assert out.empty


def test_live_arena_says_too_early_below_thirty_observations():
    outcomes = pd.DataFrame(
        {
            "forecast_id": [f"f{i}" for i in range(10)],
            "horizon": 20,
            "regime": "normal",
            "session": SESSIONS[-10:],
            "model_family": "lgbm-core",
            "model_version": "v1",
            "hit": [1.0] * 7 + [0.0] * 3,
            "baseline_hit": [1.0] * 5 + [0.0] * 5,
            "brier": 0.2,
            "baseline_brier": 0.25,
            "covered": 1.0,
        }
    )
    arena = live_arena(outcomes)
    assert not arena.empty
    assert set(arena["verdict"]) == {"too_early"}
    assert arena["live"].all()


def test_a_saved_forecast_is_never_overwritten(tmp_path, monkeypatch):
    """A megjelenítés előtt lementett becslés utólag nem módosulhat (spec/06, 1. lépés)."""
    from datetime import UTC

    from pipeline.config import RAW_BUCKET
    from pipeline.forecast import run as forecast_run
    from pipeline.ingest.storage import LocalStorage

    storage = LocalStorage(tmp_path)
    storage.ensure_private_bucket(RAW_BUCKET)
    storage.upload(
        RAW_BUCKET, forecast_run.package_path(TODAY), b"az elso csomag", "application/octet-stream"
    )

    # Ha mégis megpróbálná újraszámolni, ezen a ponton elhasalna — de nem szabad idáig jutnia.
    monkeypatch.setattr(
        forecast_run,
        "load_models",
        lambda _storage: (_ for _ in ()).throw(AssertionError("nem szabad újraszámolni")),
    )
    result = forecast_run.run(storage, datetime(2026, 9, 19, 23, 0, tzinfo=UTC))

    assert result["status"] == "already_saved"
    assert storage.download(RAW_BUCKET, forecast_run.package_path(TODAY)) == b"az elso csomag"
