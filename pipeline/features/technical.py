"""Papíronkénti technikai feature-ök (spec/06, 4. fejezet).

Minden feature a t napon csak a t napig (bezárólag) ismert adatból készül:
gördülő ablak, `ewm(adjust=False)` és `shift` — soha nem központosított ablak
és soha nem `bfill`. Ezt a `tests/test_features.py` szintetikus adaton,
a jövő megváltoztatásával ellenőrzi.

Az árak teljes hozamra igazítottak (`tr_close`, lásd `pipeline.corporate`),
a nyitó/min/max ugyanazzal a szorzóval ugyanarra az alapra hozva — különben
egy osztalék napján minden indikátor ugrana.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ANNUALIZE = np.sqrt(252)


def _adjusted_ohlc(g: pd.DataFrame) -> pd.DataFrame:
    factor = g["tr_close"] / g["close"]
    return pd.DataFrame(
        {
            "open": g["open"] * factor,
            "high": g["high"] * factor,
            "low": g["low"] * factor,
            "close": g["tr_close"],
            "volume": g["volume"],
        },
        index=g.index,
    )


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder-féle RSI (0–100)."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def instrument_features(g: pd.DataFrame) -> pd.DataFrame:
    """Egy papír idősorából (dátum szerint rendezve) a feature-tábla."""
    a = _adjusted_ohlc(g)
    c = a["close"]
    logc = np.log(c)
    r1 = logc.diff()

    ema = {n: c.ewm(span=n, adjust=False, min_periods=n).mean() for n in (12, 20, 26, 50, 200)}
    macd = ema[12] - ema[26]
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    vol_med = a["volume"].rolling(20).median()

    out = pd.DataFrame(
        {
            "ret_1": r1,
            "ret_5": logc.diff(5),
            "ret_20": logc.diff(20),
            "ret_60": logc.diff(60),
            "vol_20": r1.rolling(20).std() * ANNUALIZE,
            "vol_60": r1.rolling(60).std() * ANNUALIZE,
            # 12-1 hónapos momentum: az utolsó hónap kimarad (rövid távú visszafordulás).
            "mom_252_21": logc.shift(21) - logc.shift(252),
            "rsi_14": _rsi(c),
            "macd_hist": (macd - signal) / c,
            "ema_dist_20": np.log(c / ema[20]),
            "ema_dist_50": np.log(c / ema[50]),
            "ema_dist_200": np.log(c / ema[200]),
            "volume_anomaly_20": np.log(a["volume"].replace(0, np.nan) / vol_med.replace(0, np.nan)),
            "bb_width_20": 4 * std20 / sma20,
            "gap_1": np.log(a["open"] / c.shift(1)),
            "history_sessions": np.arange(1, len(g) + 1),
        },
        index=g.index,
    )
    return out


def compute_technical(prices: pd.DataFrame) -> pd.DataFrame:
    """Az összes papír technikai feature-jei; a kimenet kulcsa (instrument_id, date)."""
    ordered = prices.sort_values(["instrument_id", "date"]).reset_index(drop=True)
    parts = []
    for instrument_id, g in ordered.groupby("instrument_id", sort=False):
        f = instrument_features(g)
        f.insert(0, "instrument_id", instrument_id)
        f.insert(1, "date", g["date"].to_numpy())
        parts.append(f)
    out = pd.concat(parts, ignore_index=True)
    # float32: a feature-tábla mérete a felére esik, a modell pontossága nem változik
    # (a LightGBM amúgy is float32-re konvertál).
    numeric = out.select_dtypes("float64").columns
    return out.astype({c: "float32" for c in numeric})


def add_cross_sectional(features: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """Keresztmetszeti feature-ök: minden napon csak az aznapi értékekből.

    - `sector_rel_20`: a papír 20 napos hozama mínusz a szektora mediánja
      (csak részvényeknél; az ETF-eknek nincs szektor-csoportja).
    - `breadth_50`: a részvények hány százaléka van az 50 napos EMA felett.
    """
    meta = universe.set_index("instrument_id")[["asset_class", "sector"]]
    f = features.join(meta, on="instrument_id")
    equity = f["asset_class"] == "equity"
    sector_median = f[equity].groupby(["date", "sector"])["ret_20"].transform("median")
    f["sector_rel_20"] = np.nan
    f.loc[equity, "sector_rel_20"] = f.loc[equity, "ret_20"] - sector_median
    above = (f.loc[equity, "ema_dist_50"] > 0).where(f.loc[equity, "ema_dist_50"].notna())
    breadth = above.groupby(f.loc[equity, "date"]).mean().rename("breadth_50")
    f = f.join(breadth, on="date")
    return f.drop(columns=["asset_class", "sector"])
