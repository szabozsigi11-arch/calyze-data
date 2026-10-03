"""Sokk-jelzés a kötvény-becslésen (`docs/kotveny.md`, 7. fejezet).

Idősor-szinten az elmozdulás a 20 napos szórás 2,5-szerese fölött; a piaci
jel (`curve_broad`) az öt futamidő együttes kimozdulása. A „hozam-árból”
számol, így a log-változás a hozamváltozás / 100. Visszatartás nincs.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from pipeline.bonds.features import TENORS
from pipeline.fx.shocks import _sigma_moves
from pipeline.shocks.detect import CROSS_SIGMA, MOVE_SIGMA

#: Ennyi futamidő mozgása kell a piaci jelhez (az 5-ből).
BROAD_MIN = 3


def attach(frame: pd.DataFrame, prices: pd.DataFrame, universe: pd.DataFrame, day: date) -> pd.DataFrame:
    out = frame.copy()
    try:
        moves = _sigma_moves(prices, day)
        signal = {r.instrument_id: "move" if r.move > MOVE_SIGMA else "" for r in moves.itertuples()}
        tickers = universe.set_index("instrument_id")["ticker"]
        tenors = moves[moves["instrument_id"].map(tickers).isin(TENORS)]
        broad = int((tenors["move_s60"] > CROSS_SIGMA).sum()) >= BROAD_MIN
        out["shock_status"] = "ok"
        out["shock_signals"] = out["instrument_id"].map(signal).fillna("")
        out["shock_market"] = "curve_broad" if broad else ""
        out["shock_scope"] = "global_macro" if broad else None
        out["shock_tracked"] = True
    except Exception:  # noqa: BLE001 — a jelzés kiesése nem állíthatja meg a becslést
        out["shock_status"] = "failed"
        out["shock_tracked"] = False
    out["withheld"] = False
    return out
