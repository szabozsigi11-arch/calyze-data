"""Deviza feature-ök és rezsim (`docs/fx-modell.md`, 1–2. fejezet).

A technikai feature-ök a részvényekéi, a volumen- és rés-oszlop nélkül
(naponta egy fixálás van). A keresztmetszeti rész a dollár-index; a makro a
fixálás napja előtti utolsó ismert értékkel csatlakozik.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.features.regime import regime_from_returns
from pipeline.features.technical import compute_technical
from pipeline.ingest.fx import FX_PRICES_PREFIX
from pipeline.ingest.partitions import read_partition
from pipeline.ingest.storage import Storage

CALENDAR = "TARGET"
#: A dollár erősödése felé előjelezve (1. fejezet).
USD_PAIRS = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1, "USDCAD": 1, "USDCHF": 1, "USDJPY": 1}
MIN_REGIME_HISTORY = 252
MACRO_FFILL_DAYS = 5
DROPPED = ("volume_anomaly_20", "gap_1")
FX_REGIME_PATH = "regime_fx_daily.parquet"
EMPTY_ACTIONS = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])


def load_fx_prices(storage: Storage, years: list[int]) -> pd.DataFrame:
    frames = [read_partition(storage, y, FX_PRICES_PREFIX) for y in years]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(["instrument_id", "date"]).reset_index(drop=True)


def usd_returns(prices: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """A hét dolláros pár napi log változása, a dollár erősödése felé előjelezve."""
    tickers = universe.set_index("instrument_id")["ticker"]
    wide = (
        prices.assign(ticker=prices["instrument_id"].map(tickers))
        .pivot(index="date", columns="ticker", values="close")
        .sort_index()
    )
    cols = [t for t in USD_PAIRS if t in wide.columns]
    rets = np.log(wide[cols]).diff()
    return rets * pd.Series({t: USD_PAIRS[t] for t in cols})


def fx_regime(prices: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    rets = usd_returns(prices, universe)
    rets["USD_INDEX"] = rets.mean(axis=1, skipna=False)
    return regime_from_returns(rets, "USD_INDEX", list(USD_PAIRS), MIN_REGIME_HISTORY)


def add_usd_index(features: pd.DataFrame, prices: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """`usd_ret_20`: a dollár-index 20 napos változása, minden párra az aznapi érték."""
    index = usd_returns(prices, universe).mean(axis=1, skipna=False)
    usd_ret_20 = index.rolling(20).sum().rename("usd_ret_20")
    return features.join(usd_ret_20, on="date")


def add_macro_before(features: pd.DataFrame, macro: pd.DataFrame | None) -> pd.DataFrame:
    """A makro a fixálás napja ELŐTTI naptári nap utolsó ismert értékével (2. fejezet)."""
    cols = ["vix", "vix_chg_20", "yield_10y", "yield_curve_10y2y", "dollar_ret_20"]
    if macro is None or macro.empty:
        return features.assign(**{c: np.nan for c in cols})
    m = macro.copy()
    m.index = pd.to_datetime(m.index)
    m["vix_chg_20"] = np.log(m["vix"] / m["vix"].shift(20))
    m["dollar_ret_20"] = np.log(m["dollar_index"] / m["dollar_index"].shift(20))
    days = pd.date_range(m.index.min(), max(pd.Timestamp(max(features["date"])), m.index.max()), freq="D")
    daily = m[cols].reindex(days).ffill(limit=MACRO_FFILL_DAYS).shift(1)
    daily.index = daily.index.date
    return features.join(daily, on="date")


def build_fx_features(
    prices: pd.DataFrame, universe: pd.DataFrame, regime: pd.DataFrame, macro: pd.DataFrame | None
) -> pd.DataFrame:
    priced = prices.assign(tr_close=prices["close"], volume=prices["volume"].fillna(0.0))
    feats = compute_technical(priced).drop(columns=list(DROPPED))
    feats = add_usd_index(feats, prices, universe)
    feats = add_macro_before(feats, macro)
    return feats.join(regime.set_index("date")[["stress", "regime"]], on="date")
