"""Twelve Data — második tartalék, ingyenes kulccsal (`TWELVE_DATA_API_KEY`).

Napi 800 hívás, percenként 8. A záróárat felosztásra igazítva (`adjust=splits`)
és teljesen igazítva (`adjust=all`) is lekérjük: így ugyanazt a két oszlopot
adja, mint a többi forrás. Eseménylistát nem ad, ezért ha ez a forrás
szolgált ki egy papírt, a felosztás-ellenőrzés a következő futásra marad.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import requests

from pipeline.ingest.providers.base import (
    BaseProvider,
    ProviderBlockedError,
    ProviderResult,
    ProviderUnavailableError,
    RateLimit,
)

BASE_URL = "https://api.twelvedata.com/time_series"


class TwelveDataProvider(BaseProvider):
    name = "twelvedata"
    # Egy papír két hívás; 8/perc keret mellett 16 másodpercenként egy papír.
    rate_limit = RateLimit(min_interval_seconds=16.0, max_tickers_per_request=1, max_requests_per_run=60)

    def __init__(self, api_key: str | None) -> None:
        super().__init__()
        self._key = api_key

    def _get(self, ticker: str, start: date, end: date, adjust: str) -> list[dict[str, str]]:
        response = requests.get(
            BASE_URL,
            params={
                "symbol": ticker,
                "interval": "1day",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "adjust": adjust,
                "outputsize": 5000,
                "order": "ASC",
                "apikey": self._key,
            },
            timeout=30,
        )
        body = (
            response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        )
        code = int(body.get("code", response.status_code)) if isinstance(body, dict) else response.status_code
        if code in (401, 403):
            raise ProviderBlockedError(f"twelvedata {code} (kulcs vagy tiltás)")
        if code == 429:
            raise ProviderUnavailableError("twelvedata 429 (kvóta)")
        if code == 404 or body.get("status") == "error":
            return []
        if response.status_code != 200:
            raise ProviderUnavailableError(f"twelvedata HTTP {response.status_code}")
        return list(body.get("values", []))

    def _fetch_chunk(self, tickers: list[str], start: date, end: date) -> ProviderResult:
        if not self._key:
            raise ProviderUnavailableError("nincs TWELVE_DATA_API_KEY")
        ticker = tickers[0]
        split_adj = self._get(ticker, start, end, "splits")
        if not split_adj:
            return ProviderResult(pd.DataFrame(), pd.DataFrame())
        self._wait()
        full_adj = self._get(ticker, start, end, "all")
        return self.parse(split_adj, full_adj, ticker)

    @staticmethod
    def parse(split_adj: list[dict[str, str]], full_adj: list[dict[str, str]], ticker: str) -> ProviderResult:
        prices = pd.DataFrame(split_adj).rename(columns={"datetime": "date"})
        adj = pd.DataFrame(full_adj).rename(columns={"datetime": "date", "close": "adj_close"})
        if adj.empty:
            prices["adj_close"] = float("nan")
        else:
            prices = prices.merge(adj[["date", "adj_close"]], on="date", how="left")
        prices["ticker"] = ticker
        prices["date"] = pd.to_datetime(prices["date"])
        return ProviderResult(prices=prices, actions=pd.DataFrame())
