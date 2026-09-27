"""M5 — Szerkezettörés és karakterváltás (`docs/minta-definiciok-2.md`, 1. fejezet).

A szerkezet a két-két utolsó FELISMERT pivotból áll. A töréskor a szerkezetet
a törés előtti állapotból olvassuk: a mai záróár nem változtathatja meg azt a
kontextust, amiben a saját törését értékeljük.

Egy csúcs a felismerése napján még nem törhet: a felismerés azt jelenti, hogy
az utána következő öt nap egyike sem ment fölé, a záróár tehát sem.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from pipeline.patterns.common import Pivot, pivots

VARIANTS = ("bos", "choch", "neutral")


def trend_state(highs: Sequence[float], lows: Sequence[float]) -> str:
    """Emelkedő, csökkenő vagy semleges a két-két utolsó pivotból (időrendben)."""
    if len(highs) < 2 or len(lows) < 2:
        return "neutral"
    h0, h1 = highs[-2], highs[-1]
    l0, l1 = lows[-2], lows[-1]
    if h1 > h0 and l1 > l0:
        return "up"
    if h1 < h0 and l1 < l0:
        return "down"
    return "neutral"


def events(frame: pd.DataFrame, found: Sequence[Pivot] | None = None) -> list[tuple[int, str, str, str]]:
    """(napindex, szabály, bontás, irány) a törésekre."""
    close = frame["close"].to_numpy(dtype="float64")
    by_day: dict[int, list[Pivot]] = {}
    for p in found if found is not None else pivots(frame):
        by_day.setdefault(p.known_at, []).append(p)

    highs: list[float] = []
    lows: list[float] = []
    # A legutóbbi csúcs és völgy, és hogy eltört-e már (egy pivot egyszer törhet).
    last_high: float | None = None
    last_low: float | None = None
    high_broken = low_broken = True
    out: list[tuple[int, str, str, str]] = []

    for t in range(len(close)):
        # A ma felismert pivotok a mai nap ismeretei (a mai záró után tudjuk),
        # de a mai záróval nem törhetők (lásd a modul leírását).
        for p in sorted(by_day.get(t, []), key=lambda x: x.index):
            if p.kind == "high":
                highs.append(p.price)
                last_high, high_broken = p.price, False
            else:
                lows.append(p.price)
                last_low, low_broken = p.price, False

        state = trend_state(highs, lows)
        if last_high is not None and not high_broken and close[t] > last_high:
            high_broken = True
            variant = "bos" if state == "up" else "choch" if state == "down" else "neutral"
            out.append((t, "structure_break_up", variant, "long"))
        if last_low is not None and not low_broken and close[t] < last_low:
            low_broken = True
            variant = "bos" if state == "down" else "choch" if state == "up" else "neutral"
            out.append((t, "structure_break_down", variant, "short"))
    return out
