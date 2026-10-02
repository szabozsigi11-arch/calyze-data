"""Sokk-jelzés a deviza-becslésen (`docs/fx-arenak.md`, 3. fejezet).

Pár-szinten csak az elmozdulás (volumen és rés nincs); a piaci jel a hét
dolláros pár együttes kimozdulása. Visszatartás devizán nincs.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from pipeline.fx.features import USD_PAIRS
from pipeline.shocks.detect import CROSS_SIGMA, MOVE_SIGMA

#: Ennyi dolláros pár mozgása kell a piaci jelhez (a 7-ből).
BROAD_MIN = 4


def _sigma_moves(prices: pd.DataFrame, day: date) -> pd.DataFrame:
    rows = []
    for instrument, g in prices[prices["date"] <= day].sort_values("date").groupby("instrument_id"):
        g = g.tail(62)
        if len(g) < 22 or g["date"].iloc[-1] != day:
            continue
        r = np.log(g["close"].astype("float64")).diff()
        past = r.iloc[:-1].dropna()
        s20, s60, today = float(past.tail(20).std()), float(past.tail(60).std()), abs(float(r.iloc[-1]))
        rows.append(
            {
                "instrument_id": instrument,
                "move": today / s20 if s20 > 0 else np.nan,
                "move_s60": today / s60 if s60 > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows, columns=["instrument_id", "move", "move_s60"])


def attach(frame: pd.DataFrame, prices: pd.DataFrame, universe: pd.DataFrame, day: date) -> pd.DataFrame:
    out = frame.copy()
    try:
        moves = _sigma_moves(prices, day)
        signal = {r.instrument_id: "move" if r.move > MOVE_SIGMA else "" for r in moves.itertuples()}
        tickers = universe.set_index("instrument_id")["ticker"]
        usd = moves[moves["instrument_id"].map(tickers).isin(USD_PAIRS)]
        broad = int((usd["move_s60"] > CROSS_SIGMA).sum()) >= BROAD_MIN
        out["shock_status"] = "ok"
        out["shock_signals"] = out["instrument_id"].map(signal).fillna("")
        out["shock_market"] = "usd_broad" if broad else ""
        out["shock_scope"] = "global_macro" if broad else None
        out["shock_tracked"] = True
    except Exception:  # noqa: BLE001 — a jelzés kiesése nem állíthatja meg a becslést
        out["shock_status"] = "failed"
        out["shock_tracked"] = False
    out["withheld"] = False
    return out
