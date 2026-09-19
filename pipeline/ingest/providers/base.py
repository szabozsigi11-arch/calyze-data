"""A források közös szerződése (a Kalibra élesben kipróbált rétegéből átvéve).

Minden forrás ugyanazt adja: napi OHLCV + korrigált záróár, tickerrel, és
külön a vállalati eseményeket (osztalék, felosztás), ha a forrás ismeri őket.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

import pandas as pd

from pipeline.ingest.schema import conform_provider_frame, empty_actions
from pipeline.log import get_logger

log = get_logger(__name__)


class ProviderUnavailableError(RuntimeError):
    """A forrás most nem használható (kulcs hiányzik, kvóta elfogyott, kitiltott) — jöhet a következő."""


class ProviderBlockedError(ProviderUnavailableError):
    """A forrás bot-védelmet vagy tiltást adott vissza.

    Külön típus, mert infrastruktúra-hiba, nem „nincs adat”: ha üres
    eredménynek vennénk, a jelentésben hiányzó papírként látszana.
    """


@dataclass(frozen=True)
class RateLimit:
    min_interval_seconds: float = 0.0
    max_tickers_per_request: int = 1
    max_requests_per_run: int | None = None


@dataclass
class ProviderResult:
    prices: pd.DataFrame
    actions: pd.DataFrame


class BaseProvider(ABC):
    name: str = "base"
    rate_limit: RateLimit = RateLimit()
    #: ismeri-e a forrás az osztalékot és a felosztást
    reports_actions: bool = False

    def __init__(self) -> None:
        self._last_request_at = 0.0
        self._requests = 0

    @abstractmethod
    def _fetch_chunk(self, tickers: list[str], start: date, end: date) -> ProviderResult:
        """Egy adag letöltése; `end` bezárólag."""

    def fetch(self, tickers: list[str], start: date, end: date) -> ProviderResult:
        prices: list[pd.DataFrame] = []
        actions: list[pd.DataFrame] = []
        size = max(1, self.rate_limit.max_tickers_per_request)
        for i in range(0, len(tickers), size):
            limit = self.rate_limit.max_requests_per_run
            if limit is not None and self._requests >= limit:
                log.warning("provider_budget_reached", provider=self.name, skipped=len(tickers) - i)
                break
            self._wait()
            result = self._fetch_chunk(tickers[i : i + size], start, end)
            if not result.prices.empty:
                prices.append(result.prices)
            if not result.actions.empty:
                actions.append(result.actions)
        price_frame = (
            conform_provider_frame(pd.concat(prices, ignore_index=True), self.name)
            if prices
            else pd.DataFrame()
        )
        action_frame = pd.concat(actions, ignore_index=True) if actions else empty_actions()
        return ProviderResult(prices=price_frame, actions=action_frame)

    def _wait(self) -> None:
        gap = self.rate_limit.min_interval_seconds
        if gap > 0:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < gap:
                time.sleep(gap - elapsed)
        self._last_request_at = time.monotonic()
        self._requests += 1
