"""Kripto feature-ök és rezsim (`docs/kripto-modell.md`, 1–2. fejezet).

A technikai feature-ök a részvényekével azonosak (`pipeline.features.technical`);
a keresztmetszeti rész más (`breadth_50`, `btc_rel_20`, szektor nincs), a
makro a kripto-nap végén már ismert utolsó értékkel csatlakozik.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.features.regime import regime_from_returns
from pipeline.features.technical import compute_technical
from pipeline.ingest.partitions import CRYPTO_PRICES_PREFIX, read_partition
from pipeline.ingest.storage import Storage

CALENDAR = "24/7"
MARKET = "BTC-USD"
#: Az első 10 papír a rangsorban, amelynek múltja 2017-12-31-ig elkezdődik (1. fejezet).
REGIME_BASKET = [
    "BTC-USD",
    "ETH-USD",
    "XRP-USD",
    "BNB-USD",
    "ZEC-USD",
    "DOGE-USD",
    "ADA-USD",
    "TRX-USD",
    "LINK-USD",
    "LTC-USD",
]
MIN_REGIME_HISTORY = 365
#: A makro legfeljebb ennyi napig töltődik előre (hétvége, ünnep).
MACRO_FFILL_DAYS = 5
CRYPTO_REGIME_PATH = "regime_crypto_daily.parquet"
EMPTY_ACTIONS = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])


def load_crypto_prices(storage: Storage, years: list[int]) -> pd.DataFrame:
    frames = [read_partition(storage, y, CRYPTO_PRICES_PREFIX) for y in years]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(["instrument_id", "date"]).reset_index(drop=True)


def crypto_regime(prices: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """A kripto-rezsim a BTC volatilitásából és a 10-es kosár összefonódásából."""
    tickers = universe.set_index("instrument_id")["ticker"]
    wide = (
        prices.assign(ticker=prices["instrument_id"].map(tickers))
        .pivot(index="date", columns="ticker", values="close")
        .sort_index()
    )
    rets = np.log(wide[[t for t in REGIME_BASKET if t in wide.columns]]).diff()
    return regime_from_returns(rets, MARKET, REGIME_BASKET, MIN_REGIME_HISTORY)


def add_crypto_cross_sectional(features: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """`breadth_50` és `btc_rel_20`, minden napon csak az aznapi értékekből."""
    btc_id = universe.loc[universe["ticker"] == MARKET, "instrument_id"].iloc[0]
    above = (features["ema_dist_50"] > 0).where(features["ema_dist_50"].notna())
    breadth = above.groupby(features["date"]).mean().rename("breadth_50")
    btc = features.loc[features["instrument_id"] == btc_id].set_index("date")["ret_20"].rename("btc_ret_20")
    out = features.join(breadth, on="date").join(btc, on="date")
    out["btc_rel_20"] = out["ret_20"] - out["btc_ret_20"]
    return out.drop(columns=["btc_ret_20"])


def add_macro_asof(features: pd.DataFrame, macro: pd.DataFrame | None) -> pd.DataFrame:
    """A részvényes makro-feature-ök a kripto-napra: az utolsó ismert érték, legfeljebb 5 napig.

    A makrotábla napja már egy session késleltetéssel készül; a kripto-nap
    24:00 UTC-kor zár, a NYSE után, tehát az aznapi sor is ismert.
    """
    cols = ["vix", "vix_chg_20", "yield_10y", "yield_curve_10y2y", "dollar_ret_20"]
    if macro is None or macro.empty:
        return features.assign(**{c: np.nan for c in cols})
    m = macro.copy()
    m.index = pd.to_datetime(m.index)
    m["vix_chg_20"] = np.log(m["vix"] / m["vix"].shift(20))
    m["dollar_ret_20"] = np.log(m["dollar_index"] / m["dollar_index"].shift(20))
    days = pd.date_range(m.index.min(), max(pd.Timestamp(max(features["date"])), m.index.max()), freq="D")
    daily = m[cols].reindex(days).ffill(limit=MACRO_FFILL_DAYS)
    daily.index = daily.index.date
    return features.join(daily, on="date")


def build_crypto_features(
    prices: pd.DataFrame, universe: pd.DataFrame, regime: pd.DataFrame, macro: pd.DataFrame | None
) -> pd.DataFrame:
    """A teljes kripto feature-tábla: technikai + keresztmetszeti + makro + rezsim."""
    priced = prices.assign(tr_close=prices["close"])
    feats = compute_technical(priced)
    feats = add_crypto_cross_sectional(feats, universe)
    feats = add_macro_asof(feats, macro)
    return feats.join(regime.set_index("date")[["stress", "regime"]], on="date")
