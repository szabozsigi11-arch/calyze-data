"""Tanítómátrix: feature-ök + célváltozó (spec/06, 2. fejezet).

A célváltozó **log teljes hozam** a t naptól a t+h session zárásáig — nem
nyers ár: nyers áron a modell megtanulná visszaadni az előző napi árat, ami
hamis pontosságnak látszana.

A címke a jövőből jön, ezért a felosztásnál kötelező a purge és az embargo
(lásd `split.py`): a t napi sor címkéje a t+h napig tart, tehát a t..t+h
közötti napok nem lehetnek egyszerre tanító és teszt oldalon.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.corporate import total_return_prices
from pipeline.model.config import HORIZONS, MIN_HISTORY_SESSIONS

#: Ezek nem feature-ök, csak azonosítók vagy címkék.
NON_FEATURES = ("instrument_id", "date", "regime", "history_sessions")


def feature_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c not in NON_FEATURES and not c.startswith("y_")]


def add_targets(features: pd.DataFrame, prices: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Hozzáteszi a horizontonkénti jövőbeli log teljes hozamot (`y_5`, `y_20`, `y_60`)."""
    tr = prices.assign(tr_close=total_return_prices(prices, actions))
    tr = tr.sort_values(["instrument_id", "date"])[["instrument_id", "date", "tr_close"]]
    tr["log_tr"] = np.log(tr["tr_close"])
    out = features.merge(tr[["instrument_id", "date", "log_tr"]], on=["instrument_id", "date"], how="left")
    ordered = out.sort_values(["instrument_id", "date"])
    for h in HORIZONS:
        future = ordered.groupby("instrument_id", sort=False)["log_tr"].shift(-h)
        ordered[f"y_{h}"] = future - ordered["log_tr"]
    return ordered.drop(columns=["log_tr"]).reset_index(drop=True)


def trainable(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """A tanításra és mérésre alkalmas sorok: van címke és van elég előzmény."""
    mask = frame[f"y_{horizon}"].notna() & (frame["history_sessions"] >= MIN_HISTORY_SESSIONS)
    return frame[mask]


def matrix(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    return frame.loc[:, columns].to_numpy(dtype="float32")
