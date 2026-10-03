"""Kötvény (7. fázis): naptár, letöltés, „hozam-ár”, kiértékelés, sokk-jel."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from pipeline.assetspec import bonds
from pipeline.bonds.calendar import bond_days, is_bond_day, last_bond_day, offset, snapshot_at
from pipeline.bonds.features import as_price
from pipeline.bonds.forecast import package_path, to_yield, too_late
from pipeline.config import RAW_BUCKET
from pipeline.crypto.publish import run as publish
from pipeline.crypto.resolve import load_outcomes, run
from pipeline.forecast.run import _package_bytes
from pipeline.ingest import bonds as ingest
from pipeline.ingest.partitions import PRICE_SCHEMA, partition_path, to_parquet
from pipeline.ingest.storage import LocalStorage
from pipeline.publish.run import DISPLAY_BUCKET
from pipeline.universe import load_bonds_universe

TEN, SPREAD = "CZ00702", "CZ00704"  # UST10Y, UST10Y2Y
DAY = date(2026, 10, 5)  # hétfő (az univerzum 10-03-tól érvényes)


def test_kotvenynap_naptar_es_felvetel():
    assert not is_bond_day(date(2026, 4, 3))  # nagypéntek
    assert not is_bond_day(date(2026, 10, 12))  # Columbus-nap
    assert is_bond_day(date(2026, 10, 13))
    assert offset(date(2026, 10, 9), 1) == date(2026, 10, 13)
    # 15:30 ET nyáron 19:30 UTC; a közlés 18:00 ET (22:00 UTC) után számít.
    assert snapshot_at(date(2026, 10, 2)) == datetime(2026, 10, 2, 19, 30, tzinfo=UTC)
    assert last_bond_day(datetime(2026, 10, 2, 21, 0, tzinfo=UTC)) == date(2026, 10, 1)
    assert last_bond_day(datetime(2026, 10, 2, 23, 15, tzinfo=UTC)) == date(2026, 10, 2)


def test_meredekseg_ket_oszlop_kulonbsege_es_negativ_is_ok():
    curve = pd.DataFrame(
        {
            "Date": [date(2026, 10, 1)],
            "3 Mo": [4.0],
            "2 Yr": [4.5],
            "5 Yr": [4.1],
            "10 Yr": [4.2],
            "30 Yr": [4.6],
        }
    )
    out = ingest.series(curve, load_bonds_universe(), datetime(2026, 10, 2, tzinfo=UTC)).set_index(
        "instrument_id"
    )
    assert len(out) == 7
    assert out.loc[SPREAD, "close"] == pytest.approx(-0.3)
    assert out.loc["CZ00705", "close"] == pytest.approx(0.5)  # 30 év − 5 év
    assert (out["quality"] == "ok").all()
    assert out["volume"].isna().all()


def test_a_naptaron_kivuli_nap_kimarad_a_hiany_latszik(tmp_path, monkeypatch):
    days = [date(2026, 10, 8), date(2026, 10, 12), date(2026, 10, 13)]  # 10-09 hiányzik, 10-12 Columbus

    def fake(year: int, timeout: float = 60) -> pd.DataFrame:
        cols = {"3 Mo": 4.0, "2 Yr": 4.5, "5 Yr": 4.1, "10 Yr": 4.2, "30 Yr": 4.6}
        return pd.DataFrame([{"Date": d, **cols} for d in days if d.year == year])

    monkeypatch.setattr(ingest, "fetch_year", fake)
    summary = ingest.run("daily", LocalStorage(tmp_path), datetime(2026, 10, 14, 12, tzinfo=UTC))
    assert summary["off_calendar_days"] == ["2026-10-12"]
    assert "2026-10-09" in summary["missing_bond_days"]
    assert summary["rows"] == 14


def test_hozam_ar_oda_vissza_pontos_negativ_meredeksegnel_is():
    y = pd.DataFrame({"close": [-0.85, 0.01, 4.25]})
    p = as_price(y)
    assert (p["close"] > 0).all()
    # A log-változás a hozamváltozás / 100.
    assert np.log(p["close"].iloc[2] / p["close"].iloc[1]) == pytest.approx((4.25 - 0.01) / 100)
    frame = pd.DataFrame({c: p["close"] for c in ("close", "price_low", "price_high", "expected_price")})
    assert to_yield(frame)["close"].tolist() == pytest.approx([-0.85, 0.01, 4.25])


def test_a_felvetel_utan_6_oran_belul_elo():
    assert not too_late(date(2026, 10, 2), datetime(2026, 10, 3, 1, 15, tzinfo=UTC))
    assert too_late(date(2026, 10, 2), datetime(2026, 10, 3, 1, 45, tzinfo=UTC))


def yields() -> pd.DataFrame:
    rows = []
    for k, iid in enumerate([TEN, SPREAD]):
        for i, d in enumerate(bond_days(date(2026, 10, 1), date(2026, 10, 16))):
            v = 4.2 + i / 100 if k == 0 else -0.3 - i / 100
            rows.append(
                {
                    "instrument_id": iid,
                    "date": d,
                    "open": v,
                    "high": v,
                    "low": v,
                    "close": v,
                    "adj_close": v,
                    "volume": float("nan"),
                    "source": "treasury",
                    "fetched_at": pd.Timestamp("2026-10-09", tz="UTC"),
                    "quality": "ok",
                }
            )
    return pd.DataFrame(rows)


def forecasts() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "forecast_id": ["b1", "b2"],
            "instrument_id": [TEN, SPREAD],
            "session": [DAY, DAY],
            "target_session": [offset(DAY, 5)] * 2,
            "horizon": [5, 5],
            "regime": "normal",
            "model_family": "lgbm-bonds",
            "model_version": "v1",
            "prob_up": [0.6, 0.6],
            "baseline_prob": [0.5, 0.5],
            "band_low": [-0.001, -0.001],
            "band_high": [0.001, 0.001],
        }
    )


class NoJournal:
    def __getattr__(self, name: str) -> object:
        raise AssertionError("kötvényre nincs tézis-kiértékelés")


def test_kotveny_lezarasa_hozamvaltozassal_es_kulon_mappaba(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.upload(
        RAW_BUCKET, partition_path(2026, "prices_bonds_daily"), to_parquet(yields(), PRICE_SCHEMA), "x"
    )
    storage.upload(RAW_BUCKET, package_path(DAY), _package_bytes(forecasts()), "x")
    # 5 kötvénynap hétfőtől: a Columbus-nap kimarad, így október 13.
    assert offset(DAY, 5) == date(2026, 10, 13)
    summary = run(storage, datetime(2026, 10, 13, 23, 15, tzinfo=UTC), NoJournal(), spec=bonds())  # type: ignore[arg-type]
    assert summary["resolved_now"] == 2
    out = load_outcomes(storage, [2026], "outcomes-bonds").set_index("instrument_id")
    # A 10 éves hozam 5 nap alatt 5 bp-t emelkedett: a log-változás 0,0005.
    assert out.loc[TEN, "actual_return"] == pytest.approx(0.0005)
    assert out.loc[TEN, "hit"] == 1.0
    assert out.loc[SPREAD, "hit"] == 0.0

    assert publish(storage, datetime(2026, 10, 13, 23, 30, tzinfo=UTC), spec=bonds())["status"] == "published"
    written = set(storage.list(DISPLAY_BUCKET, "bonds"))
    assert {"bonds/latest.json", "bonds/evidence.json", "bonds/record.json"} <= written
    # A papír-nézet a hozamot mutatja (%), nem a transzformált „árat”.
    payload = json.loads(storage.download(DISPLAY_BUCKET, f"instruments/{SPREAD}.json") or b"{}")
    assert payload["candles"][-1]["c"] == pytest.approx(-0.40)
    assert payload["instrument"]["exchange_calendar"] == "UST"


def test_kotveny_sokk_harom_futamido_kell():
    from pipeline.bonds.features import TENORS
    from pipeline.bonds.shocks import BROAD_MIN, attach

    u = load_bonds_universe()
    ids = list(u[u["ticker"].isin(TENORS)]["instrument_id"])
    days = bond_days(date(2026, 6, 1), date(2026, 9, 25))
    rng = np.random.default_rng(7)
    rows = []
    for k, iid in enumerate(ids):
        y = 4.0 + np.cumsum(rng.normal(0, 0.03, len(days)))
        if k < BROAD_MIN:
            y[-1] = y[-2] + 0.40
        rows += [{"instrument_id": iid, "date": d, "close": v} for d, v in zip(days, y, strict=True)]
    prices = as_price(pd.DataFrame(rows))
    out = attach(pd.DataFrame({"instrument_id": ids}), prices, u, days[-1]).set_index("instrument_id")
    assert set(out["shock_market"]) == {"curve_broad"}
    assert out.loc[ids[0], "shock_signals"] == "move"
    assert not out["withheld"].any()
