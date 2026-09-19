"""Forráslánc: sorban próbálja a forrásokat, papír-szinten kiegészítve egymást.

Egy papír adata onnan jön, ahonnan először sikerült megszerezni; ami kimaradt,
azt a következő forrás próbálja. A jelentés megmondja, melyik forrás mennyit
adott, és mi maradt ki — ez kerül a futás összefoglalójába.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from pipeline.ingest.providers.base import BaseProvider, ProviderBlockedError, ProviderUnavailableError
from pipeline.log import get_logger

log = get_logger(__name__)


class NoDataError(RuntimeError):
    """Egyetlen forrás sem adott adatot. Hiányos adattal nem dolgozunk tovább."""


@dataclass
class ChainReport:
    requested: int = 0
    tickers_by_source: dict[str, int] = field(default_factory=dict)
    rows_by_source: dict[str, int] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "requested": self.requested,
            "tickers_by_source": self.tickers_by_source,
            "rows_by_source": self.rows_by_source,
            "failures": self.failures,
            "missing": self.missing,
        }


@dataclass
class ChainResult:
    prices: pd.DataFrame
    actions: pd.DataFrame
    #: ticker → a forrás neve, amelyik kiszolgálta
    served_by: dict[str, str]
    report: ChainReport


class ProviderChain:
    def __init__(self, providers: list[BaseProvider]) -> None:
        if not providers:
            raise ValueError("A forráslánc nem lehet üres.")
        self.providers = providers

    def fetch(self, tickers: list[str], start: date, end: date) -> ChainResult:
        report = ChainReport(requested=len(tickers))
        remaining = list(dict.fromkeys(tickers))
        prices: list[pd.DataFrame] = []
        actions: list[pd.DataFrame] = []
        served_by: dict[str, str] = {}

        for provider in self.providers:
            if not remaining:
                break
            try:
                result = provider.fetch(remaining, start, end)
            except ProviderBlockedError as error:
                report.failures[provider.name] = f"kitiltva: {error}"
                log.warning("provider_blocked", provider=provider.name, error=str(error))
                continue
            except ProviderUnavailableError as error:
                report.failures[provider.name] = str(error)
                log.warning("provider_unavailable", provider=provider.name, error=str(error))
                continue
            except Exception as error:  # noqa: BLE001 — egy forrás hibája nem állíthatja meg a láncot
                report.failures[provider.name] = f"{type(error).__name__}: {error}"
                log.warning("provider_failed", provider=provider.name, error=type(error).__name__)
                continue

            if result.prices.empty:
                report.tickers_by_source[provider.name] = 0
                continue
            served = set(result.prices["ticker"].unique())
            prices.append(result.prices)
            if not result.actions.empty:
                acts = result.actions[result.actions["ticker"].isin(served)].copy()
                acts["source"] = provider.name
                actions.append(acts)
            for t in served:
                served_by[t] = provider.name
            report.tickers_by_source[provider.name] = len(served)
            report.rows_by_source[provider.name] = len(result.prices)
            remaining = [t for t in remaining if t not in served]
            log.info(
                "provider_served", provider=provider.name, tickers=len(served), still_missing=len(remaining)
            )

        report.missing = remaining
        if not prices:
            raise NoDataError(f"Egyetlen forrás sem adott adatot. Hibák: {report.failures or 'nincs'}")
        return ChainResult(
            prices=pd.concat(prices, ignore_index=True),
            actions=pd.concat(actions, ignore_index=True) if actions else pd.DataFrame(),
            served_by=served_by,
            report=report,
        )
