"""Kötvény feature-ök és rezsim (`docs/kotveny.md`, 4–5. fejezet).

A tárban a hozam %-ban áll. A modell és a mérés egy „ár”-transzformációt lát:
`exp(hozam/100)`, így a log-változás pontosan a hozamváltozás / 100, és a
negatív meredekség sem gond. A megjelenítés a nyers hozamot mutatja.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.features.regime import regime_from_returns
from pipeline.features.technical import compute_technical
from pipeline.fx.features import add_macro_before
from pipeline.ingest.bonds import BONDS_PRICES_PREFIX
from pipeline.ingest.partitions import read_partition
from pipeline.ingest.storage import Storage

CALENDAR = "UST"
TENORS = ("UST3M", "UST2Y", "UST5Y", "UST10Y", "UST30Y")
MARKET = "UST10Y"
MIN_REGIME_HISTORY = 252
DROPPED = ("volume_anomaly_20", "gap_1")
BONDS_REGIME_PATH = "regime_bonds_daily.parquet"
EMPTY_ACTIONS = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])


def load_bond_yields(storage: Storage, years: list[int]) -> pd.DataFrame:
    """A nyers hozamok (%), a megjelenítéshez."""
    frames = [read_partition(storage, y, BONDS_PRICES_PREFIX) for y in years]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(["instrument_id", "date"]).reset_index(drop=True)


def as_price(yields: pd.DataFrame) -> pd.DataFrame:
    """`exp(hozam/100)`: a modell és a mérés „ára” (4. fejezet)."""
    out = yields.copy()
    for col in ("open", "high", "low", "close", "adj_close"):
        if col in out:
            out[col] = np.exp(out[col].astype("float64") / 100.0)
    return out


def load_bond_prices(storage: Storage, years: list[int]) -> pd.DataFrame:
    """A transzformált „ár” — a kiértékelés ebből számol hozamváltozást."""
    raw = load_bond_yields(storage, years)
    return as_price(raw) if not raw.empty else raw


def _wide_changes(yields: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    tickers = universe.set_index("instrument_id")["ticker"]
    wide = (
        yields.assign(ticker=yields["instrument_id"].map(tickers))
        .pivot(index="date", columns="ticker", values="close")
        .sort_index()
    )
    return wide.diff() / 100.0


def bond_regime(yields: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    changes = _wide_changes(yields, universe)
    cols = [t for t in TENORS if t in changes.columns]
    return regime_from_returns(changes[cols], MARKET, list(cols), MIN_REGIME_HISTORY)


def add_curve(features: pd.DataFrame, yields: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """`level_10y`, `slope_10y2y` és a meredekség 20 napos változása, minden idősorra."""
    tickers = universe.set_index("instrument_id")["ticker"]
    wide = (
        yields.assign(ticker=yields["instrument_id"].map(tickers))
        .pivot(index="date", columns="ticker", values="close")
        .sort_index()
    )
    curve = pd.DataFrame(index=wide.index)
    curve["level_10y"] = wide.get("UST10Y")
    curve["slope_10y2y"] = wide.get("UST10Y2Y")
    curve["slope_chg_20"] = curve["slope_10y2y"] - curve["slope_10y2y"].shift(20)
    return features.join(curve, on="date")


def build_bond_features(
    yields: pd.DataFrame, universe: pd.DataFrame, regime: pd.DataFrame, macro: pd.DataFrame | None
) -> pd.DataFrame:
    priced = as_price(yields)
    priced = priced.assign(tr_close=priced["close"], volume=priced["volume"].fillna(0.0))
    feats = compute_technical(priced).drop(columns=list(DROPPED))
    feats = add_curve(feats, yields, universe)
    feats = add_macro_before(feats, macro)
    return feats.join(regime.set_index("date")[["stress", "regime"]], on="date")
