"""Deviza: TARGET-napos lezárás, saját család és saját megjelenítési mappa."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from pipeline.assetspec import fx
from pipeline.config import RAW_BUCKET
from pipeline.crypto.publish import run as publish
from pipeline.crypto.resolve import load_outcomes, run
from pipeline.forecast.run import _package_bytes
from pipeline.fx.calendar import offset, target_days
from pipeline.fx.forecast import package_path, too_late
from pipeline.ingest.fx import FX_PRICES_PREFIX
from pipeline.ingest.partitions import PRICE_SCHEMA, partition_path, to_parquet
from pipeline.ingest.storage import LocalStorage
from pipeline.publish.run import DISPLAY_BUCKET

DAY = date(2026, 9, 25)  # péntek


def prices() -> pd.DataFrame:
    rows = []
    for k, iid in enumerate(["CZ00674", "CZ00680"]):  # EURUSD, GBPUSD
        for i, d in enumerate(target_days(date(2026, 9, 22), date(2026, 10, 9))):
            rate = 1.1 + (i if k == 0 else -i) / 100
            rows.append(
                {
                    "instrument_id": iid,
                    "date": d,
                    "open": rate,
                    "high": rate,
                    "low": rate,
                    "close": rate,
                    "adj_close": rate,
                    "volume": float("nan"),
                    "source": "ecb",
                    "fetched_at": pd.Timestamp("2026-10-09", tz="UTC"),
                    "quality": "ok",
                }
            )
    return pd.DataFrame(rows)


def forecasts() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "forecast_id": ["f1", "f2"],
            "instrument_id": ["CZ00674", "CZ00680"],
            "session": [DAY, DAY],
            "target_session": [offset(DAY, 5)] * 2,
            "horizon": [5, 5],
            "regime": "normal",
            "model_family": "lgbm-fx",
            "model_version": "v1",
            "prob_up": [0.6, 0.6],
            "baseline_prob": [0.5, 0.5],
            "band_low": [-0.1, -0.1],
            "band_high": [0.1, 0.1],
        }
    )


def test_a_fixalas_utan_6_oran_belul_elo():
    assert not too_late(date(2026, 10, 2), datetime(2026, 10, 2, 15, 20, tzinfo=UTC))
    assert too_late(date(2026, 10, 2), datetime(2026, 10, 2, 18, 30, tzinfo=UTC))


def test_deviza_lezarasa_target_nappal_es_kulon_mappaba(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.upload(
        RAW_BUCKET, partition_path(2026, FX_PRICES_PREFIX), to_parquet(prices(), PRICE_SCHEMA), "x"
    )
    storage.upload(RAW_BUCKET, package_path(DAY), _package_bytes(forecasts()), "x")
    # 5 TARGET-nap péntektől: október 2. (hétvége nélkül), a fixálás 12:10 UTC.
    assert offset(DAY, 5) == date(2026, 10, 2)
    assert run(storage, datetime(2026, 10, 2, 11, 0, tzinfo=UTC), spec=fx())["resolved_now"] == 0
    summary = run(storage, datetime(2026, 10, 2, 15, 20, tzinfo=UTC), spec=fx())
    assert summary["resolved_now"] == 2
    out = load_outcomes(storage, [2026], "outcomes-fx").set_index("instrument_id")
    assert out.loc["CZ00674", "hit"] == 1.0
    assert out.loc["CZ00680", "hit"] == 0.0

    result = publish(storage, datetime(2026, 10, 2, 15, 30, tzinfo=UTC), spec=fx())
    assert result["status"] == "published"
    written = set(storage.list(DISPLAY_BUCKET, "fx"))
    assert {"fx/latest.json", "fx/evidence.json", "fx/record.json", "fx/instruments.json"} <= written
    assert not storage.list(DISPLAY_BUCKET, "crypto")
