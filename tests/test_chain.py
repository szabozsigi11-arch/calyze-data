from datetime import date

import pandas as pd
import pytest

from pipeline.ingest.chain import NoDataError, ProviderChain
from pipeline.ingest.providers.base import BaseProvider, ProviderBlockedError, ProviderResult
from tests.conftest import price_rows

DAYS = [date(2026, 9, 17), date(2026, 9, 18)]


class Fake(BaseProvider):
    def __init__(self, name, serves=(), error=None):
        super().__init__()
        self.name = name
        self.serves = set(serves)
        self.error = error
        self.asked: list[list[str]] = []

    def _fetch_chunk(self, tickers, start, end):
        self.asked.append(list(tickers))
        if self.error:
            raise self.error
        frames = [price_rows(t, DAYS) for t in tickers if t in self.serves]
        return ProviderResult(pd.concat(frames) if frames else pd.DataFrame(), pd.DataFrame())


def test_blocked_primary_falls_back_and_is_reported():
    primary = Fake("yfinance", error=ProviderBlockedError("bot-ellenőrzés"))
    backup = Fake("tiingo", serves={"AAPL", "SPY"})
    result = ProviderChain([primary, backup]).fetch(["AAPL", "SPY"], DAYS[0], DAYS[-1])
    assert result.served_by == {"AAPL": "tiingo", "SPY": "tiingo"}
    assert result.report.failures["yfinance"].startswith("kitiltva")
    assert result.report.missing == []


def test_backup_only_gets_what_primary_missed():
    primary = Fake("yfinance", serves={"AAPL"})
    backup = Fake("tiingo", serves={"AAPL", "SPY"})
    result = ProviderChain([primary, backup]).fetch(["AAPL", "SPY"], DAYS[0], DAYS[-1])
    assert backup.asked == [["SPY"]]
    assert result.served_by == {"AAPL": "yfinance", "SPY": "tiingo"}


def test_missing_tickers_are_reported_not_hidden():
    result = ProviderChain([Fake("yfinance", serves={"AAPL"})]).fetch(["AAPL", "GONE"], DAYS[0], DAYS[-1])
    assert result.report.missing == ["GONE"]


def test_no_data_at_all_stops_the_run():
    with pytest.raises(NoDataError):
        ProviderChain([Fake("a", error=RuntimeError("x")), Fake("b")]).fetch(["AAPL"], DAYS[0], DAYS[-1])
