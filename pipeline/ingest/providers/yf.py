"""yfinance — az elsődleges forrás, kulcs nélkül.

Nem hivatalos API: bármikor elromolhat, ezért áll mögötte tartalék. A
blokkolásnál kivétel helyett üres táblát ad — ezt itt kifejezetten hibának
vesszük, különben a lánc sosem lépne a tartalékra.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from pipeline.ingest.providers.base import BaseProvider, ProviderResult, ProviderUnavailableError, RateLimit


class YFinanceProvider(BaseProvider):
    name = "yfinance"
    rate_limit = RateLimit(min_interval_seconds=1.0, max_tickers_per_request=50)
    reports_actions = True

    def _fetch_chunk(self, tickers: list[str], start: date, end: date) -> ProviderResult:
        raw = yf.download(
            tickers=tickers,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),  # a yfinance `end`-je kizáró
            interval="1d",
            auto_adjust=False,  # kell a nyers záró ÉS az Adj Close is
            actions=True,
            progress=False,
            threads=True,
            group_by="ticker",
        )
        if raw is None or raw.empty:
            raise ProviderUnavailableError(f"üres válasz {len(tickers)} papírra — vélhető korlátozás")
        return self.to_long(raw, tickers)

    @staticmethod
    def to_long(raw: pd.DataFrame, tickers: list[str]) -> ProviderResult:
        prices: list[pd.DataFrame] = []
        actions: list[pd.DataFrame] = []
        multi = isinstance(raw.columns, pd.MultiIndex)
        for ticker in tickers:
            if multi:
                if ticker not in raw.columns.get_level_values(0):
                    continue
                part = raw[ticker].copy()
            else:
                part = raw.copy()
            part = part.dropna(how="all", subset=[c for c in ("Open", "High", "Low", "Close") if c in part])
            if part.empty:
                continue
            part = part.reset_index().rename(
                columns={
                    "Date": "date",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Adj Close": "adj_close",
                    "Volume": "volume",
                    "Dividends": "dividend",
                    "Stock Splits": "split_ratio",
                }
            )
            part["ticker"] = ticker
            prices.append(part[["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]])
            if {"dividend", "split_ratio"} <= set(part.columns):
                ev = part[(part["dividend"].fillna(0) != 0) | (part["split_ratio"].fillna(0) != 0)]
                if not ev.empty:
                    actions.append(ev[["ticker", "date", "dividend", "split_ratio"]])
        return ProviderResult(
            prices=pd.concat(prices, ignore_index=True) if prices else pd.DataFrame(),
            actions=pd.concat(actions, ignore_index=True) if actions else pd.DataFrame(),
        )
