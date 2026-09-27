"""R2 sokk-detektor és R3 besorolás, napvégi adatból (docs/sokk-detektor.md).

A küszöbök a dokumentumban rögzültek a mérés előtt; itt csak átírva
állnak. A detektor nem jósol irányt: azt mondja meg, mikor bizonytalanabb
minden a szokásosnál.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from pipeline.corporate import total_return_prices

VOLUME_Z = 3.0
GAP_SIGMA = 2.0
MOVE_SIGMA = 2.5
VIX_JUMP = 0.20
CROSS_SIGMA = 2.5
CROSS_MIN = 3
SHARE = 0.30
SECTOR_MIN = 5
#: öt eszközosztály egy-egy ETF-je
BASKET = {"SPY": "equity", "TLT": "bonds", "GLD": "gold", "USO": "oil", "UUP": "dollar"}

SCOPES = ("instrument", "sector", "country", "global_macro")


@dataclass(frozen=True)
class MarketShock:
    signals: tuple[str, ...]
    vix_change: float | None
    cross: tuple[str, ...]
    scope: str | None
    tractability: str
    withheld: bool
    extra: dict[str, float] = field(default_factory=dict)


def instrument_signals(prices: pd.DataFrame, actions: pd.DataFrame, session: date) -> pd.DataFrame:
    """Papíronként a három jel az `S` napra; a múlt csak `S` előttről."""
    cols = ["instrument_id", "volume_z", "gap_sigma", "move_sigma", "signals"]
    if prices.empty:
        return pd.DataFrame(columns=cols)
    p = prices[prices["date"] <= session].sort_values(["instrument_id", "date"]).copy()
    p["tr"] = total_return_prices(p, actions)
    splits = set()
    if not actions.empty and "split_ratio" in actions:
        s = actions[
            (actions["date"] == session) & actions["split_ratio"].notna() & (actions["split_ratio"] != 1)
        ]
        splits = set(s["instrument_id"])

    rows = []
    for instrument, g in p.groupby("instrument_id", sort=False):
        g = g.tail(62)
        if len(g) < 22 or g["date"].iloc[-1] != session:
            continue
        r = np.log(g["tr"].astype("float64")).diff()
        past = r.iloc[:-1].dropna()
        today = float(r.iloc[-1])
        s60 = float(past.tail(60).std())
        s20 = float(past.tail(20).std())
        vol = g["volume"].astype("float64")
        v_past = vol.iloc[:-1].tail(60)
        v_std = float(v_past.std())
        volume_z = (float(vol.iloc[-1]) - float(v_past.mean())) / v_std if v_std > 0 else np.nan
        prev_close = float(g["close"].iloc[-2])
        open_ = float(g["open"].iloc[-1]) if pd.notna(g["open"].iloc[-1]) else np.nan
        gap = abs(np.log(open_ / prev_close)) / s60 if s60 > 0 and prev_close > 0 and open_ > 0 else np.nan
        if instrument in splits:
            gap = np.nan
        move = abs(today) / s20 if s20 > 0 else np.nan
        signals = [
            name
            for name, value, limit in (
                ("volume", volume_z, VOLUME_Z),
                ("gap", gap, GAP_SIGMA),
                ("move", move, MOVE_SIGMA),
            )
            if pd.notna(value) and value > limit
        ]
        rows.append(
            {
                "instrument_id": instrument,
                "volume_z": volume_z,
                "gap_sigma": gap,
                "move_sigma": move,
                "signals": ",".join(signals),
            }
        )
    return pd.DataFrame(rows, columns=cols)


def market_signals(
    prices: pd.DataFrame,
    actions: pd.DataFrame,
    universe: pd.DataFrame,
    macro: pd.DataFrame | None,
    session: date,
) -> tuple[list[str], float | None, list[str]]:
    """A VIX-ugrás és a keresztpiaci kimozdulás."""
    signals: list[str] = []
    vix_change: float | None = None
    if macro is not None and "vix" in macro:
        vix = macro["vix"].dropna()
        days = pd.to_datetime(pd.Series(vix.index)).dt.date.to_numpy()
        vix = vix[days <= session]
        if len(vix) >= 2 and float(vix.iloc[-2]) > 0:
            vix_change = float(vix.iloc[-1]) / float(vix.iloc[-2]) - 1
            if vix_change > VIX_JUMP:
                signals.append("vix")

    ids = universe.set_index("ticker")["instrument_id"]
    cross: list[str] = []
    for ticker in BASKET:
        if ticker not in ids.index:
            continue
        g = (
            prices[(prices["instrument_id"] == ids[ticker]) & (prices["date"] <= session)]
            .sort_values("date")
            .tail(62)
        )
        if len(g) < 22 or g["date"].iloc[-1] != session:
            continue
        tr = total_return_prices(g, actions)
        r = np.log(tr.astype("float64")).diff()
        s60 = float(r.iloc[:-1].dropna().tail(60).std())
        if s60 > 0 and abs(float(r.iloc[-1])) / s60 > CROSS_SIGMA:
            cross.append(ticker)
    if len(cross) >= CROSS_MIN:
        signals.append("cross_market")
    return signals, vix_change, cross


def classify(
    inst: pd.DataFrame, market: list[str], vix_change: float | None, cross: list[str], universe: pd.DataFrame
) -> tuple[pd.DataFrame, MarketShock]:
    """R3: hatókör, tartósság, kezelhetőség, és a visszatartás."""
    out = inst.merge(universe[["instrument_id", "asset_class", "sector"]], on="instrument_id", how="left")
    flagged = out["signals"].fillna("") != ""
    equities = out["asset_class"] == "equity"
    country = equities.sum() > 0 and (flagged & equities).sum() / equities.sum() >= SHARE

    sector_hit: set[str] = set()
    for sector, g in out[out["sector"].notna()].groupby("sector"):
        if len(g) >= SECTOR_MIN and (g["signals"] != "").mean() >= SHARE:
            sector_hit.add(str(sector))

    if market:
        market_scope: str | None = "global_macro"
    elif country:
        market_scope = "country"
    else:
        market_scope = None
    tractability = "unknowable" if ("vix" in market and "cross_market" in market) else "priceable"
    withheld = tractability == "unknowable" and market_scope in ("country", "global_macro")

    def scope(row: pd.Series) -> str | None:
        if market_scope is not None:
            return market_scope
        if row["signals"] == "":
            return None
        if row["sector"] in sector_hit:
            return "sector"
        return "instrument"

    def persistence(row: pd.Series) -> str | None:
        n = len([s for s in str(row["signals"]).split(",") if s])
        if market or n >= 2:
            return "days"
        return "intraday_noise" if n == 1 else None

    out["shock_scope"] = out.apply(scope, axis=1) if not out.empty else []
    out["shock_persistence"] = out.apply(persistence, axis=1) if not out.empty else []
    out["shock_tractability"] = tractability
    out["withheld"] = withheld
    return (
        out.drop(columns=["asset_class", "sector"]),
        MarketShock(tuple(market), vix_change, tuple(cross), market_scope, tractability, withheld),
    )


def attach_shocks(frame: pd.DataFrame, classified: pd.DataFrame, shock: MarketShock) -> pd.DataFrame:
    """A becslés-sorokhoz a jelek és a besorolás (a lenyomat alá kerülnek)."""
    keep = ["instrument_id", "signals", "shock_scope", "shock_persistence", "shock_tractability"]
    merged = frame.merge(classified[keep], on="instrument_id", how="left")
    merged = merged.rename(columns={"signals": "shock_signals"})
    merged["shock_signals"] = merged["shock_signals"].fillna("")
    merged["shock_market"] = ",".join(shock.signals)
    merged["shock_tractability"] = merged["shock_tractability"].fillna(shock.tractability)
    merged["withheld"] = shock.withheld
    return merged


def detect(
    prices: pd.DataFrame,
    actions: pd.DataFrame,
    universe: pd.DataFrame,
    macro: pd.DataFrame | None,
    session: date,
) -> tuple[pd.DataFrame, MarketShock]:
    inst = instrument_signals(prices, actions, session)
    market, vix_change, cross = market_signals(prices, actions, universe, macro, session)
    return classify(inst, market, vix_change, cross, universe)
