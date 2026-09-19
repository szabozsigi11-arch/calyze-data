"""Tiingo — első tartalék, ingyenes kulccsal (`TIINGO_API_KEY`).

A kerete szűk (óránként kb. 50 különböző papír), ezért nem tömeges letöltésre,
hanem hiánypótlásra való.
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

BASE_URL = "https://api.tiingo.com/tiingo/daily"


class TiingoProvider(BaseProvider):
    name = "tiingo"
    rate_limit = RateLimit(min_interval_seconds=0.3, max_tickers_per_request=1, max_requests_per_run=45)
    reports_actions = True

    def __init__(self, api_key: str | None) -> None:
        super().__init__()
        self._key = api_key

    def _fetch_chunk(self, tickers: list[str], start: date, end: date) -> ProviderResult:
        if not self._key:
            raise ProviderUnavailableError("nincs TIINGO_API_KEY")
        ticker = tickers[0]
        response = requests.get(
            f"{BASE_URL}/{ticker.replace('.', '-')}/prices",
            params={"startDate": start.isoformat(), "endDate": end.isoformat()},
            headers={"Authorization": f"Token {self._key}"},
            timeout=30,
        )
        if response.status_code == 404:
            return ProviderResult(pd.DataFrame(), pd.DataFrame())
        if response.status_code in (401, 403):
            raise ProviderBlockedError(f"tiingo HTTP {response.status_code} (kulcs vagy tiltás)")
        if response.status_code == 429:
            raise ProviderUnavailableError("tiingo HTTP 429 (kvóta)")
        if response.status_code != 200:
            raise ProviderUnavailableError(f"tiingo HTTP {response.status_code}")
        return self.parse(response.json(), ticker)

    @staticmethod
    def parse(payload: list[dict[str, object]], ticker: str) -> ProviderResult:
        if not payload:
            return ProviderResult(pd.DataFrame(), pd.DataFrame())
        raw = pd.DataFrame(payload)
        # A Tiingo a nyers és a korrigált oszlopokat is adja (close és adjClose).
        # Csak a kellőket vesszük át, külön névvel — ha az adjOpen is „open”
        # lenne, két azonos nevű oszlop keletkezne (Kalibra, 2026-09-12).
        prices = raw.loc[:, ["date", "open", "high", "low", "close", "volume", "adjClose"]].rename(
            columns={"adjClose": "adj_close"}
        )
        prices["ticker"] = ticker
        prices["date"] = pd.to_datetime(prices["date"], utc=True).dt.tz_localize(None)
        actions = pd.DataFrame()
        if {"divCash", "splitFactor"} <= set(raw.columns):
            ev = raw[(raw["divCash"].fillna(0) != 0) | (raw["splitFactor"].fillna(1) != 1)]
            if not ev.empty:
                actions = pd.DataFrame(
                    {
                        "ticker": ticker,
                        "date": pd.to_datetime(ev["date"], utc=True).dt.tz_localize(None),
                        "dividend": ev["divCash"].astype(float),
                        # A Tiingo 1-et ad, ha nem volt felosztás; mi 0-t (mint a yfinance).
                        "split_ratio": ev["splitFactor"].astype(float).where(ev["splitFactor"] != 1, 0.0),
                    }
                )
        return ProviderResult(prices=prices, actions=actions)
