"""A kripto-letöltés (`pipeline/ingest/crypto.py`): hétvége marad, hiány jelölve, külön fájl."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from pipeline.ingest.chain import ChainReport, ChainResult
from pipeline.ingest.crypto import canonical, missing_dates, missing_days, run
from pipeline.ingest.partitions import CRYPTO_PRICES_PREFIX, PRICES_PREFIX, existing_years, read_partition
from pipeline.ingest.storage import LocalStorage

NOW = datetime(2026, 10, 4, 0, 30, tzinfo=UTC)  # vasárnap éjjel: a szombati nap már lezárult


def prices(symbol: str, days: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": symbol,
            "date": [date.fromisoformat(d) for d in days],
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "adj_close": 1.5,
            "volume": 1e6,
            "source": "yfinance",
        }
    )


def test_a_hetvege_kereskedesi_nap_a_mai_le_nem_zart_nap_nem():
    raw = prices("BTC-USD", ["2026-10-02", "2026-10-03", "2026-10-04"])  # péntek, szombat, vasárnap (nyitott)
    out = canonical(raw, {"BTC-USD": "CZ00621"}, date(2026, 10, 3), NOW)
    assert [str(d) for d in out["date"]] == ["2026-10-02", "2026-10-03"]


def test_hiany_jelolve_nem_potolva():
    frame = pd.DataFrame(
        {
            "instrument_id": ["CZ00621"] * 3 + ["CZ00622"] * 2,
            "date": [date(2026, 9, d) for d in (1, 2, 4)] + [date(2026, 9, d) for d in (3, 4)],
        }
    )
    # A CZ00622 csak szeptember 3-án indult: előtte nincs „hiánya”.
    assert missing_days(frame, date(2026, 9, 1), date(2026, 9, 4)) == {"CZ00621": 1}


def test_kulon_fajlba_ir_a_reszvenyes_tar_erintetlen(tmp_path, monkeypatch):
    days = [f"2026-09-{d:02d}" for d in range(20, 31)] + ["2026-10-01", "2026-10-02", "2026-10-03"]
    fake = ChainResult(
        prices=pd.concat([prices("BTC-USD", days), prices("ETH-USD", days)], ignore_index=True),
        actions=pd.DataFrame(),
        served_by={"BTC-USD": "yfinance", "ETH-USD": "yfinance"},
        report=ChainReport(requested=2, tickers_by_source={"yfinance": 2}),
    )

    class Chain:
        def fetch(self, *_a: object) -> ChainResult:
            return fake

    monkeypatch.setattr("pipeline.ingest.crypto.build_chain", lambda: Chain())
    storage = LocalStorage(tmp_path)
    summary = run("daily", storage, NOW)
    assert summary["last_session"] == "2026-10-03"
    assert existing_years(storage, CRYPTO_PRICES_PREFIX) == [2026]
    assert existing_years(storage, PRICES_PREFIX) == []
    stored = read_partition(storage, 2026, CRYPTO_PRICES_PREFIX)
    assert set(stored["instrument_id"]) == {"CZ00621", "CZ00622"}
    assert date(2026, 9, 26) in set(stored["date"])  # szombat


def test_hianyzo_napok_datum_szerint():
    frame = pd.DataFrame(
        {
            "instrument_id": ["CZ00621"] * 2 + ["CZ00622"] * 2,
            "date": [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 1), date(2026, 9, 2)],
        }
    )
    assert missing_dates(frame, date(2026, 9, 1), date(2026, 9, 3)) == {"2026-09-03": 2}
