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

    def contributions(self, frame: pd.DataFrame, top: int = 6) -> list[list[dict[str, float | str]]]:
        return [[{"feature": "mom_20", "value": 0.01}] for _ in range(len(frame))]

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
    """A megjelenítés előtt lementett becslés utólag nem módosulhat (spec/06, 1. lépés).

    A futás a session kiválasztása UTÁN nézi meg, hogy van-e már csomag — a
    naptár szerinti napra ugyanis lehet, hogy soha nem becslünk. A teszt ezért
    a kiválasztott napot rögzíti, és onnantól figyeli: a modellhez nem nyúl
    hozzá, és a meglévő csomag változatlan marad.
    """
    from datetime import UTC

    from pipeline.config import RAW_BUCKET
    from pipeline.forecast import run as forecast_run
    from pipeline.ingest.storage import LocalStorage

    storage = LocalStorage(tmp_path)
    storage.ensure_private_bucket(RAW_BUCKET)
    storage.upload(
        RAW_BUCKET, forecast_run.package_path(TODAY), b"az elso csomag", "application/octet-stream"
    )

    # A nehéz betöltés helyett a döntést adjuk meg: a futás erre a napra
    # jutott volna. Innentől a kérdés az, hogy hozzányúl-e a meglévő csomaghoz.
    monkeypatch.setattr(forecast_run, "_load_prices", lambda *_: _prices_for(TODAY))
    monkeypatch.setattr(forecast_run, "_read_table", lambda _s, path: _stub_table(path))
    monkeypatch.setattr(forecast_run, "build_features", lambda *_args, **_kw: _features_for(TODAY))
    monkeypatch.setattr(forecast_run, "add_sector_return", lambda frame: frame)
    monkeypatch.setattr(forecast_run, "choose_session", lambda *_args, **_kw: TODAY)
    monkeypatch.setattr(
        forecast_run,
        "load_models",
        lambda _storage: (_ for _ in ()).throw(AssertionError("nem szabad újraszámolni")),
    )
    result = forecast_run.run(storage, datetime(2026, 9, 19, 23, 0, tzinfo=UTC))

    assert result["status"] == "already_saved"
    assert storage.download(RAW_BUCKET, forecast_run.package_path(TODAY)) == b"az elso csomag"


def _prices_for(session):
    return pd.DataFrame({"instrument_id": ["CZ00001"], "date": [session], "close": [100.0]})


def _features_for(session):
    return pd.DataFrame({"instrument_id": ["CZ00001"], "date": [session], "history_sessions": [500]})


def _stub_table(path):
    """A rezsim-tábla létezik, a többi nem kell ehhez a teszthez."""
    return pd.DataFrame({"date": [], "regime": []}) if "regime" in str(path) else None


def test_a_becsles_az_adat_napjara_szol_nem_a_naptareira():
    """Ha a forrás kihagy egy napot, a meglévő adatra becslünk — de arra a napra."""
    from pipeline.forecast.run import choose_session

    # 2026-09-21 hétfő az utolsó zárt nap, de az adat pénteken áll meg.
    coverage = {date(2026, 9, 17): 620, date(2026, 9, 18): 620}
    assert choose_session(coverage, date(2026, 9, 21), 620) == date(2026, 9, 18)


def test_egy_papir_nem_napi_meres():
    """A forrás néha egyetlen papírra teszi közzé az aznapi sort. Az nem nap."""
    from pipeline.forecast.run import choose_session

    coverage = {date(2026, 9, 18): 620, date(2026, 9, 22): 1}
    assert choose_session(coverage, date(2026, 9, 22), 620) == date(2026, 9, 18)


def test_tul_nagy_forraskieses_utan_nem_becslunk():
    """Négy kihagyott nap után a hallgatás az őszinte válasz (spec/06)."""
    import pytest

    from pipeline.forecast.run import choose_session

    with pytest.raises(RuntimeError, match="marad el"):
        choose_session({date(2026, 9, 11): 620}, date(2026, 9, 18), 620)


def test_ha_egyetlen_napra_sincs_eleg_adat_megallunk():
    import pytest

    from pipeline.forecast.run import choose_session

    with pytest.raises(RuntimeError, match="Egyetlen napra sincs elég adat"):
        choose_session({date(2026, 9, 18): 12}, date(2026, 9, 18), 620)
