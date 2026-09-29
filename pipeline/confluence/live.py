"""A konfluencia élő panelje (`docs/konfluencia.md`, 5. fejezet).

Minden nap, minden papírra: a legutóbbi napon mely kiváltók szóltak, mely
kontextusok álltak, és a heti mérés szerint mit értek ezek a kombinációk. A
számok nem itt születnek: a heti mérés táblájából (`confluence/results.parquet`)
jönnek, változatlanul. Itt csak az dől el, melyik kombináció áll MA.

A kiváltókat és a kontextusokat ugyanaz a kód számolja, mint a mérést
(`instrument_triggers`), csak rövidebb múlton: a napi csomag öt évét kapja.
"""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from datetime import date

import pandas as pd

from pipeline.arena.signals import all_signals
from pipeline.confluence.contexts import BIT, CONTEXTS, combo_id, excluded, subsets
from pipeline.confluence.run import instrument_triggers


def standing(
    instrument: str,
    frame: pd.DataFrame,
    indicator_rows: pd.DataFrame,
    regime: Mapping[date, str],
    session: date,
) -> list[tuple[str, str, tuple[str, ...]]]:
    """(kiváltó, irány, álló kontextusok) a `session` napra; a kiváltóhoz nem illő kontextus kimarad."""
    events = instrument_triggers(instrument, frame, indicator_rows, regime)
    today = events[events["date"] == session]
    out = []
    for row in today.itertuples(index=False):
        allowed = [c for c in CONTEXTS if c not in excluded(row.trigger)]
        on = tuple(c for c in allowed if int(row.mask) & BIT[c])
        out.append((str(row.trigger), str(row.direction), on))
    # Egy kiváltó egy napon egyszer (az indikátor és a minta nem ad duplikátumot, de a biztonság kedvéért).
    return sorted(set(out))


def _stats(row: Mapping[str, object], prefix: str) -> dict[str, object] | None:
    n = row.get(f"{prefix}_n")
    if n is None or pd.isna(n):
        return None
    keys = ("n_eff", "hit", "baseline", "delta", "p", "verdict")
    out: dict[str, object] = {"n": int(n)}
    for k in keys:
        value = row.get(f"{prefix}_{k}")
        out[k] = None if value is None or (isinstance(value, float) and pd.isna(value)) else value
    return out


def panel(
    active: list[tuple[str, str, tuple[str, ...]]],
    results: pd.DataFrame | None,
    session: date,
) -> dict[str, object]:
    """A papír-csomag `confluence` része.

    Minden álló kiváltóhoz az összes olyan mért kombináció, aminek minden
    kontextusa ma áll (az 1–3 elemű részhalmazok). A mérés nélküli állapot is
    kimondódik (`measured: false`), nem marad ki csendben.
    """
    if results is None or results.empty:
        return {"session": str(session), "measured": False, "tested": 0, "active": []}
    by_key = {(str(r["combo"]), int(r["horizon"])): r for r in results.to_dict("records")}
    tested = int((results["status"] != "too_early").sum())
    horizons = sorted({int(h) for h in results["horizon"].unique()})

    items = []
    for trigger, direction, on in active:
        combos = []
        for contexts in subsets(trigger):
            if not set(contexts) <= set(on):
                continue
            cid = combo_id(trigger, contexts)
            for horizon in horizons:
                row = by_key.get((cid, horizon))
                if row is None:
                    continue
                combos.append(
                    {
                        "combo": cid,
                        "contexts": list(contexts),
                        "horizon": horizon,
                        "status": row["status"],
                        "discovery": _stats(row, "disc"),
                        "confirmation": _stats(row, "conf"),
                    }
                )
        items.append({"trigger": trigger, "direction": direction, "contexts": list(on), "combos": combos})
    return {"session": str(session), "measured": True, "tested": tested, "active": items}


def _standing_of(item: tuple[str, pd.DataFrame, pd.DataFrame, dict[date, str], date]) -> tuple[str, list]:
    instrument, frame, indicator_rows, regime, session = item
    return instrument, standing(instrument, frame, indicator_rows, regime, session)


def standing_all(
    prices: pd.DataFrame,
    regime: Mapping[date, str],
    session: date,
    workers: int | None = None,
) -> dict[str, list[tuple[str, str, tuple[str, ...]]]]:
    """Az egész univerzum mai kiváltói. A papírok függetlenek, ezért párhuzamosan."""
    data = prices.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.date
    indicators = all_signals(data)
    indicators["date"] = pd.to_datetime(indicators["date"]).dt.date
    indicators = indicators[indicators["date"] == session]
    by_instrument = {str(k): g for k, g in indicators.groupby("instrument_id")}
    empty = indicators.iloc[0:0]
    regime_dict = dict(regime)
    items = [
        (str(i), g, by_instrument.get(str(i), empty), regime_dict, session)
        for i, g in data.groupby("instrument_id", sort=True)
        if (g["date"] == session).any()
    ]
    if workers == 1 or len(items) < 8:
        return dict(_standing_of(item) for item in items)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(_standing_of, items, chunksize=4))
