"""Kripto-kiértékelés: a saját táblájába ír, a saját családjában mér, naptári nappal zár."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from pipeline.config import RAW_BUCKET
from pipeline.crypto.forecast import _package_bytes, package_path
from pipeline.crypto.resolve import LIVE_PATH, load_outcomes, run
from pipeline.features.run import _read_table
from pipeline.ingest.partitions import CRYPTO_PRICES_PREFIX, PRICE_SCHEMA, partition_path, to_parquet
from pipeline.ingest.storage import LocalStorage

DAY = date(2026, 10, 2)


def prices() -> pd.DataFrame:
    days = [DAY + timedelta(days=i) for i in range(-3, 7)]
    rows = []
    for k, inst in enumerate(["CZ00621", "CZ00622"]):
        for i, d in enumerate(days):
            close = 100.0 + (i if k == 0 else -i)
            rows.append(
                {
                    "instrument_id": inst,
                    "date": d,
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "adj_close": close,
                    "volume": 1e6,
                    "source": "yfinance",
                    "fetched_at": pd.Timestamp("2026-10-09", tz="UTC"),
                    "quality": "ok",
                }
            )
    return pd.DataFrame(rows)


def forecasts() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "forecast_id": ["f1", "f2"],
            "instrument_id": ["CZ00621", "CZ00622"],
            "session": [DAY, DAY],
            "target_session": [DAY + timedelta(days=5)] * 2,
            "horizon": [5, 5],
            "regime": ["normal", "normal"],
            "model_family": "lgbm-crypto",
            "model_version": "v1",
            "prob_up": [0.6, 0.6],
            "baseline_prob": [0.52, 0.52],
            "band_low": [-0.1, -0.1],
            "band_high": [0.1, 0.1],
        }
    )


def test_a_kripto_becsles_naptari_nappal_zarul_es_kulon_csaladban_mer(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.upload(
        RAW_BUCKET, partition_path(2026, CRYPTO_PRICES_PREFIX), to_parquet(prices(), PRICE_SCHEMA), "x"
    )
    storage.upload(RAW_BUCKET, package_path(DAY), _package_bytes(forecasts()), "x")

    # 10-07 00:00 UTC-kor zárul a 10-07-i nap; előtte nincs mit lezárni.
    early = run(storage, datetime(2026, 10, 6, 1, 0, tzinfo=UTC))
    assert early["resolved_now"] == 0

    summary = run(storage, datetime(2026, 10, 8, 0, 30, tzinfo=UTC))
    assert summary["resolved_now"] == 2
    out = load_outcomes(storage, [2026]).set_index("instrument_id")
    assert out.loc["CZ00621", "hit"] == 1.0  # emelkedett, 60%-ot mondtunk
    assert out.loc["CZ00622", "hit"] == 0.0
    arena = _read_table(storage, LIVE_PATH)
    assert arena is not None
    assert set(arena["scope"]) == {"crypto"}

    again = run(storage, datetime(2026, 10, 9, 0, 30, tzinfo=UTC))
    assert again["resolved_now"] == 0  # ami lezárult, nem íródik újra


def test_a_kripto_megjelenites_kulon_fajlokba_ir(tmp_path):
    from pipeline.crypto.publish import run as publish
    from pipeline.publish.run import DISPLAY_BUCKET

    storage = LocalStorage(tmp_path)
    storage.upload(
        RAW_BUCKET, partition_path(2026, CRYPTO_PRICES_PREFIX), to_parquet(prices(), PRICE_SCHEMA), "x"
    )
    storage.upload(RAW_BUCKET, package_path(DAY), _package_bytes(forecasts()), "x")
    run(storage, datetime(2026, 10, 8, 0, 30, tzinfo=UTC))
    result = publish(storage, datetime(2026, 10, 8, 0, 40, tzinfo=UTC))
    assert result["status"] == "published"
    written = set(storage.list(DISPLAY_BUCKET, "crypto"))
    assert {
        "crypto/latest.json",
        "crypto/instruments.json",
        "crypto/evidence.json",
        "crypto/record.json",
    } <= written
    # A részvényes fájlokhoz nem nyúl, a letöltések saját mappába mennek.
    assert storage.download(DISPLAY_BUCKET, "latest.json") is None
    assert storage.download(DISPLAY_BUCKET, "record.json") is None
    assert storage.list(DISPLAY_BUCKET, "record-crypto")
    assert not storage.list(DISPLAY_BUCKET, "record")
