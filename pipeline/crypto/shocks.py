"""Sokk-jelzés a kripto-becslésen (`docs/kripto-arenak.md`, 2. fejezet).

A papír-szintű jel a részvényes detektoré (`pipeline.shocks.detect`), a
rés-jel nélkül (24/7-es piacon nincs zárvatartás). A piaci jel a 10-es
rezsim-kosárból jön. Visszatartás kriptón az első változatban nincs.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from pipeline.crypto.features import EMPTY_ACTIONS, REGIME_BASKET
from pipeline.shocks.detect import CROSS_SIGMA, instrument_signals

#: Ennyi kosár-papír mozgása kell a piaci jelhez (a 10-ből).
BROAD_MIN = 5
SIGNALS = ("volume", "move")


def broad_count(prices: pd.DataFrame, universe: pd.DataFrame, day: date) -> int:
    """Hány kosár-papír mozgott aznap a saját 60 napos szórásának 2,5-szerese fölött."""
    ids = universe.set_index("ticker")["instrument_id"]
    moved = 0
    for ticker in REGIME_BASKET:
        if ticker not in ids.index:
            continue
        g = (
            prices[(prices["instrument_id"] == ids[ticker]) & (prices["date"] <= day)]
            .sort_values("date")
            .tail(62)
        )
        if len(g) < 22 or g["date"].iloc[-1] != day:
            continue
        r = np.log(g["close"].astype("float64")).diff()
        s60 = float(r.iloc[:-1].dropna().tail(60).std())
        if s60 > 0 and abs(float(r.iloc[-1])) / s60 > CROSS_SIGMA:
            moved += 1
    return moved


def attach(frame: pd.DataFrame, prices: pd.DataFrame, universe: pd.DataFrame, day: date) -> pd.DataFrame:
    """A jelek a becslés-sorokra; hibánál `failed`, és nem állítjuk, hogy nem volt jel."""
    out = frame.copy()
    try:
        inst = instrument_signals(prices, EMPTY_ACTIONS, day)
        keep = {
            str(r.instrument_id): ",".join(s for s in str(r.signals).split(",") if s in SIGNALS)
            for r in inst.itertuples()
        }
        broad = broad_count(prices, universe, day) >= BROAD_MIN
        out["shock_status"] = "ok"
        out["shock_signals"] = out["instrument_id"].map(keep).fillna("")
        out["shock_market"] = "crypto_broad" if broad else ""
        out["shock_scope"] = "global_macro" if broad else None
        out["shock_tracked"] = True
    except Exception:  # noqa: BLE001 — a jelzés kiesése nem állíthatja meg a becslést
        out["shock_status"] = "failed"
        out["shock_tracked"] = False
    out["withheld"] = False
    return out
