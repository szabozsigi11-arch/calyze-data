"""A forrás-adapterek leképezése — hálózat nélkül, a válaszok alakjával."""

from datetime import date

import pandas as pd

from pipeline.ingest.providers.tiingo import TiingoProvider
from pipeline.ingest.providers.twelvedata import TwelveDataProvider
from pipeline.ingest.providers.yf import YFinanceProvider
from pipeline.ingest.schema import conform_provider_frame


def test_tiingo_raw_and_adjusted_columns_do_not_collide():
    # A Tiingo a nyers és a korrigált oszlopokat is adja; a Kalibrában az
    # adjOpen → open átnevezés két azonos nevű oszlopot csinált.
    payload = [
        {
            "date": "2026-09-18T00:00:00.000Z",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10.5,
            "volume": 100,
            "adjOpen": 5,
            "adjHigh": 5.5,
            "adjLow": 4.5,
            "adjClose": 5.25,
            "adjVolume": 200,
            "divCash": 0.0,
            "splitFactor": 2.0,
        },
    ]
    result = TiingoProvider.parse(payload, "AAPL")
    conformed = conform_provider_frame(result.prices, "tiingo")
    assert list(conformed["close"]) == [10.5]
    assert list(conformed["adj_close"]) == [5.25]
    assert list(result.actions["split_ratio"]) == [2.0]


def test_tiingo_split_factor_one_means_no_split():
    payload = [
        {
            "date": "2026-09-18T00:00:00.000Z",
            "open": 1,
            "high": 1,
            "low": 1,
            "close": 1,
            "volume": 1,
            "adjClose": 1,
            "divCash": 0.25,
            "splitFactor": 1.0,
        }
    ]
    result = TiingoProvider.parse(payload, "KO")
    assert list(result.actions["split_ratio"]) == [0.0]
    assert list(result.actions["dividend"]) == [0.25]


def test_twelvedata_merges_split_and_fully_adjusted_close():
    split_adj = [
        {"datetime": "2026-09-18", "open": "10", "high": "11", "low": "9", "close": "10.5", "volume": "100"}
    ]
    full_adj = [
        {"datetime": "2026-09-18", "open": "9", "high": "10", "low": "8", "close": "9.9", "volume": "100"}
    ]
    result = TwelveDataProvider.parse(split_adj, full_adj, "MSFT")
    conformed = conform_provider_frame(result.prices, "twelvedata")
    assert list(conformed["close"]) == [10.5]
    assert list(conformed["adj_close"]) == [9.9]


def test_yfinance_wide_frame_to_long_with_actions():
    idx = pd.DatetimeIndex([pd.Timestamp("2026-09-17"), pd.Timestamp("2026-09-18")], name="Date")
    cols = pd.MultiIndex.from_product(
        [
            ["AAPL", "SPY"],
            ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"],
        ]
    )
    raw = pd.DataFrame(1.0, index=idx, columns=cols)
    raw[("AAPL", "Dividends")] = [0.0, 0.26]
    raw[("AAPL", "Stock Splits")] = 0.0
    raw[("SPY", "Dividends")] = 0.0
    raw[("SPY", "Stock Splits")] = 0.0
    result = YFinanceProvider.to_long(raw, ["AAPL", "SPY", "MISSING"])
    assert set(result.prices["ticker"]) == {"AAPL", "SPY"}
    assert len(result.prices) == 4
    assert list(result.actions["ticker"]) == ["AAPL"]
    assert pd.Timestamp(result.actions["date"].iloc[0]).date() == date(2026, 9, 18)
