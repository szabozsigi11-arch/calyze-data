"""Egy nem részvényes eszközosztály leírása (kripto, deviza).

A kiértékelés és a megjelenítés egyetlen megvalósítás (`pipeline.crypto.resolve`,
`pipeline.crypto.publish`); ez a leírás mondja meg, melyik naptárral, melyik
tárból és melyik mappába dolgozzon. Így egy javítás mindkét eszközosztályra hat.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from pipeline.ingest.storage import Storage


@dataclass(frozen=True)
class AssetSpec:
    name: str
    #: a megjelenítés és a tézis-kiértékelés naptárkódja (`24/7`, `TARGET`)
    calendar: str
    scope: str
    family: str
    version: str
    last_day: Callable[[datetime], date]
    load_prices: Callable[[Storage, list[int]], pd.DataFrame]
    load_universe: Callable[[], pd.DataFrame]
    history_start_year: int
    first_year: int
    forecasts_prefix: str
    outcomes_prefix: str
    live_path: str
    backtest_path: str
    display_prefix: str
    export_prefix: str
    #: a papír-nézet chartjának hossza (napban)
    history_days: int


def crypto() -> AssetSpec:
    from pipeline.calendar import last_closed_session
    from pipeline.crypto.features import load_crypto_prices
    from pipeline.ingest.crypto import CRYPTO_HISTORY_START
    from pipeline.universe import load_crypto_universe

    return AssetSpec(
        name="crypto",
        calendar="24/7",
        scope="crypto",
        family="lgbm-crypto",
        version="v1",
        last_day=lambda now: last_closed_session(now, "24/7"),
        load_prices=load_crypto_prices,
        load_universe=load_crypto_universe,
        history_start_year=CRYPTO_HISTORY_START.year,
        first_year=2026,
        forecasts_prefix="forecasts-crypto",
        outcomes_prefix="outcomes-crypto",
        live_path="arena/crypto_live.parquet",
        backtest_path="arena/crypto_backtest.parquet",
        display_prefix="crypto",
        export_prefix="record-crypto",
        history_days=365,
    )


def fx() -> AssetSpec:
    from pipeline.fx.calendar import last_fixing_day
    from pipeline.fx.features import load_fx_prices
    from pipeline.ingest.fx import FX_HISTORY_START
    from pipeline.universe import load_fx_universe

    return AssetSpec(
        name="fx",
        calendar="TARGET",
        scope="fx",
        family="lgbm-fx",
        version="v1",
        last_day=last_fixing_day,
        load_prices=load_fx_prices,
        load_universe=load_fx_universe,
        history_start_year=FX_HISTORY_START.year,
        first_year=2026,
        forecasts_prefix="forecasts-fx",
        outcomes_prefix="outcomes-fx",
        live_path="arena/fx_live.parquet",
        backtest_path="arena/fx_backtest.parquet",
        display_prefix="fx",
        export_prefix="record-fx",
        history_days=252,
    )
