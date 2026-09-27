"""M1 — Fibonacci-visszaesés (`docs/minta-definiciok-2.md`, 3. fejezet).

Az impulzus két felismert pivot között van, a visszaesés a következő
felismert pivotig tart, és az esemény ennek a felismerésének a napja. A négy
változat ugyanazokat a pivotokat használja; csak az ár más, amivel a mélységet
számoljuk (kanóc vagy test) — a forrás szerint ez vitatott, ezért mind a négyet
mérjük, külön.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from pipeline.patterns.common import Pivot, atr, pivots

#: Az impulzus legkisebb mérete ATR-ben.
MIN_IMPULSE_ATR = 3.0
#: Zónahatárok: (felső határ, név), növekvő sorrendben; a 0,786 fölött érvénytelen.
ZONES = ((0.382, "shallow"), (0.5, "z382"), (0.618, "z500"), (0.786, "golden"))
VARIANTS = ("wick", "body", "wick_body", "body_wick")


def zone(depth: float) -> str:
    for limit, name in ZONES:
        if depth < limit:
            return name
    return "invalid"


def _prices(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    o = frame["open"].to_numpy(dtype="float64")
    c = frame["close"].to_numpy(dtype="float64")
    return {
        "high": frame["high"].to_numpy(dtype="float64"),
        "low": frame["low"].to_numpy(dtype="float64"),
        "body_top": np.maximum(o, c),
        "body_bottom": np.minimum(o, c),
    }


def _anchor(p: dict[str, np.ndarray], variant: str, index: int, role: str, up: bool) -> float:
    """A változat szerinti ár. `role`: "start" (és a visszaesés pontja) vagy "end".

    Felfelé impulzusnál a kezdet és a visszaesés völgy, a vég csúcs; lefelé
    fordítva. A változat neve (kezdet_vég) mondja meg, melyik kanóc, melyik test.
    """
    start_kind, end_kind = {
        "wick": ("wick", "wick"),
        "body": ("body", "body"),
        "wick_body": ("wick", "body"),
        "body_wick": ("body", "wick"),
    }[variant]
    kind = start_kind if role == "start" else end_kind
    is_low = (role == "start") == up  # felfelé a kezdet völgy; lefelé a vég völgy
    if kind == "wick":
        return float(p["low"][index] if is_low else p["high"][index])
    return float(p["body_bottom"][index] if is_low else p["body_top"][index])


def events(frame: pd.DataFrame, found: Sequence[Pivot] | None = None) -> list[tuple[int, str, str, str]]:
    """(napindex, szabály, változat, irány) minden érvényes impulzus visszaesésére."""
    close = frame["close"].to_numpy(dtype="float64")
    band = atr(frame)
    prices = _prices(frame)
    ordered = sorted(found if found is not None else pivots(frame), key=lambda x: x.index)
    highs = [p for p in ordered if p.kind == "high"]
    lows = [p for p in ordered if p.kind == "low"]
    n = len(close)
    out: list[tuple[int, str, str, str]] = []

    for up in (True, False):
        ends = highs if up else lows
        starts = lows if up else highs
        for end in ends:
            start = next((s for s in reversed(starts) if s.index < end.index), None)
            back = next((s for s in starts if s.index > end.index), None)
            if start is None or back is None or back.known_at >= n:
                continue
            size_atr = band[end.index]
            if not np.isfinite(size_atr) or abs(end.price - start.price) < MIN_IMPULSE_ATR * size_atr:
                continue
            # Folytatódott az impulzus a visszaesés felismerése előtt? Akkor ez nem
            # visszaesés volt. A kanóc-csúcshoz (-mélyponthoz) mérünk, minden változatnál.
            window = close[end.index + 1 : back.known_at + 1]
            if (window > end.price).any() if up else (window < end.price).any():
                continue
            name = "fib_up" if up else "fib_down"
            direction = "long" if up else "short"
            for variant in VARIANTS:
                a = _anchor(prices, variant, start.index, "start", up)
                b = _anchor(prices, variant, end.index, "end", up)
                r = _anchor(prices, variant, back.index, "start", up)
                span = (b - a) if up else (a - b)
                if span <= 0:
                    continue
                depth = ((b - r) if up else (r - b)) / span
                out.append((back.known_at, f"{name}_{zone(depth)}", variant, direction))
    return out
