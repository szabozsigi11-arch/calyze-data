"""Piaci rezsim: calm / normal / stressed (spec/06, 5. fejezet).

A címke szabályból születik, nem kézből. Két összetevő:

1. **Volatilitás:** az S&P 500 ETF (SPY) 20 napos realizált volatilitása.
2. **Keresztpiaci összefonódás:** egy piacokon átívelő kosár (részvény USA,
   fejlett és feltörekvő piacok, hosszú kötvény, magas hozamú kötvény, arany,
   olaj, dollár) napi hozamainak átlagos **abszolút** páronkénti
   korrelációja 60 sessionre. Válságban a piacok együtt mozdulnak — az
   irány mindegy, ezért az abszolút érték.

Mindkettőt **bővülő ablakú percentilisként** mérjük: a t napi érték rangja a
t napig látott összes értékhez képest. Így a címke soha nem használ jövőbeli
eloszlást (egy teljes idősoron számolt percentilis 2008-ban már tudná, mi
történt 2020-ban). Legalább 252 session előzmény kell; addig nincs címke.

    stress = (vol_pct + corr_pct) / 2
    calm:     stress < 1/3
    stressed: stress ≥ 0,80
    normal:   a kettő között

A „stressed” küszöbe szándékosan magasabb, mint a „calm”-é: a stresszelt
napok ritkák, és a felület ott állít kellemetlen igazságot (a modell
jellemzően ott gyengébb), tehát a címkének ritkának és egyértelműnek kell lennie.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

MARKET = "SPY"
CROSS_MARKET = ["SPY", "EFA", "EEM", "TLT", "HYG", "GLD", "USO", "UUP"]
MIN_HISTORY = 252
CALM_BELOW = 1 / 3
STRESSED_FROM = 0.80


def _returns_by_ticker(prices: pd.DataFrame, universe: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    ids = universe.set_index("ticker")["instrument_id"]
    wanted = {ids[t]: t for t in tickers if t in ids.index}
    sub = prices[prices["instrument_id"].isin(wanted)]
    wide = sub.pivot(index="date", columns="instrument_id", values="tr_close").rename(columns=wanted)
    return np.log(wide).diff()


def expanding_percentile(x: pd.Series, min_periods: int = MIN_HISTORY) -> pd.Series:
    """A t napi érték rangja (0–1) a t napig látott értékek között."""
    return x.expanding(min_periods=min_periods).rank(pct=True)


def compute_regime(prices: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    rets = _returns_by_ticker(prices, universe, CROSS_MARKET)
    market_vol = rets[MARKET].rolling(20).std() * np.sqrt(252)

    pairs = [(a, b) for a, b in combinations(CROSS_MARKET, 2) if a in rets and b in rets]
    corr = pd.concat(
        [rets[a].rolling(60, min_periods=60).corr(rets[b]).abs() for a, b in pairs], axis=1
    ).mean(axis=1, skipna=False)

    vol_pct = expanding_percentile(market_vol.dropna()).reindex(rets.index)
    corr_pct = expanding_percentile(corr.dropna()).reindex(rets.index)
    stress = (vol_pct + corr_pct) / 2

    label = pd.Series(pd.NA, index=rets.index, dtype="string")
    label[stress < CALM_BELOW] = "calm"
    label[(stress >= CALM_BELOW) & (stress < STRESSED_FROM)] = "normal"
    label[stress >= STRESSED_FROM] = "stressed"

    out = pd.DataFrame(
        {
            "market_vol_20": market_vol,
            "cross_market_corr_60": corr,
            "vol_pct": vol_pct,
            "corr_pct": corr_pct,
            "stress": stress,
            "regime": label,
        }
    )
    out.index.name = "date"
    return out.reset_index()
