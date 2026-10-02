"""A hír-aréna jelzései és kimenetelei, vektorosan (`docs/hir-arena.md`).

A sokk-jeleket a napi detektor (`pipeline/shocks/detect.py`) egyetlen napra
számolja. A backtesthez minden múltbeli napra kellenek, ezért itt ugyanaz a
szabály, egyszerre az egész idősorra. Hogy valóban ugyanaz, azt teszt nézi:
tetszőleges napra ugyanazt kell adnia, mint a detektornak.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from pipeline.corporate import total_return_prices
from pipeline.events.calendar import EVENTS
from pipeline.shocks.detect import BASKET, CROSS_MIN, CROSS_SIGMA, GAP_SIGMA, MOVE_SIGMA, VIX_JUMP, VOLUME_Z

#: A kimenetel ablaka: a jelzés utáni ennyi kereskedési nap.
AFTER = 5
#: A „jelzés előtti” volatilitás ablaka (a detektor `s20`-a).
BEFORE = 20
#: A visszatartás akkor jogos, ha a SPY utána legalább ennyiszer mozgékonyabb.
WITHHOLD_RATIO = 1.5
MARKET = "SPY"


def _returns(prices: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Papíronként a napi log teljes hozam, dátum szerint rendezve."""
    p = prices.sort_values(["instrument_id", "date"]).reset_index(drop=True).copy()
    p["tr"] = total_return_prices(p, actions)
    p["r"] = np.log(p["tr"].astype("float64")).groupby(p["instrument_id"]).diff()
    return p


def instrument_frame(prices: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Minden papír-napra a három detektor-jel, a jelzés-előtti és -utáni volatilitás."""
    p = _returns(prices, actions)
    g = p.groupby("instrument_id", sort=False)
    past = g["r"].shift(1)
    # A detektor a nap ELŐTTI hozamokból számol (60 és 20 nap; rövid múltnál amennyi van, legalább 20).
    s60 = past.groupby(p["instrument_id"]).rolling(60, min_periods=20).std().reset_index(level=0, drop=True)
    s20 = past.groupby(p["instrument_id"]).rolling(20, min_periods=20).std().reset_index(level=0, drop=True)
    vol = p["volume"].astype("float64")
    v_past = vol.groupby(p["instrument_id"]).shift(1)
    v_mean = (
        v_past.groupby(p["instrument_id"]).rolling(60, min_periods=21).mean().reset_index(level=0, drop=True)
    )
    v_std = (
        v_past.groupby(p["instrument_id"]).rolling(60, min_periods=21).std().reset_index(level=0, drop=True)
    )
    prev_close = g["close"].shift(1).astype("float64")

    volume_z = (vol - v_mean) / v_std.where(v_std > 0)
    gap = np.abs(np.log(p["open"].astype("float64") / prev_close)) / s60.where(s60 > 0)
    move = np.abs(p["r"]) / s20.where(s20 > 0)
    # A felosztás napján a rés értelmetlen (a detektor is kihagyja).
    if not actions.empty and "split_ratio" in actions:
        splits = actions[actions["split_ratio"].notna() & (actions["split_ratio"] != 1)]
        split_days = set(zip(splits["instrument_id"], splits["date"], strict=True))
        on_split = [(i, d) in split_days for i, d in zip(p["instrument_id"], p["date"], strict=True)]
        gap = gap.where(~np.array(on_split, dtype=bool))
    # A detektor legalább 22 sort kér (21 hozam): előtte nincs jel.
    enough = g.cumcount() >= 21

    after = (
        p["r"]
        .groupby(p["instrument_id"])
        .rolling(AFTER, min_periods=AFTER)
        .std()
        .reset_index(level=0, drop=True)
    )
    after = after.groupby(p["instrument_id"]).shift(-AFTER)
    out = pd.DataFrame(
        {
            "instrument_id": p["instrument_id"],
            "date": p["date"],
            "volume_z": volume_z,
            "gap_sigma": gap,
            "move_sigma": move,
            # a keresztpiaci jel a 60 napos szórással mér (a detektor `market_signals`-a)
            "move_s60": np.abs(p["r"]) / s60.where(s60 > 0),
            "enough": enough,
            "sigma_before": s20,
            "vol_after": after,
        }
    )
    out["flag"] = enough & (
        (out["volume_z"] > VOLUME_Z) | (out["gap_sigma"] > GAP_SIGMA) | (out["move_sigma"] > MOVE_SIGMA)
    )
    return out


def market_frame(
    instruments: pd.DataFrame, universe: pd.DataFrame, macro: pd.DataFrame | None
) -> pd.DataFrame:
    """Naponként: VIX-ugrás, keresztpiaci jel, visszatartás, és a SPY kimenetele.

    Ugyanaz, mint a detektor `market_signals` + `classify` része: piaci jel a
    VIX-ugrás vagy legalább 3 kosár-ETF 2,5 szigmás (60 napos) mozgása;
    visszatartás, ha mindkettő szól.
    """
    ids = universe.set_index("ticker")["instrument_id"]
    spy = instruments[instruments["instrument_id"] == ids.get(MARKET)].set_index("date").sort_index()
    out = pd.DataFrame(index=spy.index)
    out["sigma_before"] = spy["sigma_before"]
    out["vol_after"] = spy["vol_after"]

    moved = []
    for ticker in BASKET:
        if ticker not in ids.index:
            continue
        etf = instruments[instruments["instrument_id"] == ids[ticker]].set_index("date")
        moved.append(((etf["move_s60"] > CROSS_SIGMA) & etf["enough"]).rename(ticker))
    cross = pd.concat(moved, axis=1).reindex(out.index).fillna(False).sum(axis=1) if moved else 0
    out["cross_count"] = cross
    out["cross"] = out["cross_count"] >= CROSS_MIN

    out["vix_change"] = np.nan
    if macro is not None and "vix" in macro:
        vix = macro["vix"].dropna()
        vix_days = pd.to_datetime(pd.Series(vix.index)).dt.date.to_numpy()
        change = pd.Series((vix / vix.shift(1) - 1).to_numpy(), index=vix_days)
        # A detektor a nap ELŐTTI két utolsó VIX-értéket nézi: ha aznap nincs érték, a legutóbbit.
        aligned = pd.merge_asof(
            pd.DataFrame({"date": pd.to_datetime(list(out.index))}),
            pd.DataFrame({"date": pd.to_datetime(list(change.index)), "vix_change": change.to_numpy()}),
            on="date",
        )
        out["vix_change"] = aligned["vix_change"].to_numpy()
    out["vix"] = out["vix_change"] > VIX_JUMP
    out["market_flag"] = out["vix"] | out["cross"]
    out["withheld"] = out["vix"] & out["cross"]
    return out


def calendar_days(sessions: list[date]) -> dict[date, list[str]]:
    """Az `S` kereskedési napok, amelyek UTÁNI első kereskedési napra hivatalos esemény esik."""
    out: dict[date, list[str]] = {}
    ordered = sorted(sessions)
    for event in EVENTS:
        # Az esemény napja vagy az utána következő első kereskedési nap (D').
        later = [s for s in ordered if s >= event.day]
        if not later:
            continue
        d_prime = later[0]
        i = ordered.index(d_prime)
        if i == 0:
            continue
        out.setdefault(ordered[i - 1], []).append(event.kind)
    return out
