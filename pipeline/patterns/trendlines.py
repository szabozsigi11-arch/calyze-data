"""M9 — Trendvonalak (`docs/minta-definiciok-2.md`, 5. fejezet).

Egy vonal két szomszédos, felismert pivoton megy át, és a második
felismerésétől él. Az érintéseket és a törést napról napra, csak az aznap
ismert ATR-rel számoljuk; egy vonal egyszer törhet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
import pandas as pd

from pipeline.patterns.common import Pivot, atr, pivots

#: Az érintés tűrése ATR-ben.
TOUCH_TOLERANCE = 0.5
#: A törés küszöbe ATR-ben (ugyanaz, mint a szintek lejáratáé).
BREAK_ATR = 1.0
#: Két érintés között legalább ennyi nap.
COOLDOWN = 5
#: Törés nélkül ennyi nap után a vonal lejár (a második pivot napjától).
LIFETIME = 252


@dataclass
class Line:
    up: bool
    i1: int
    p1: float
    i2: int
    p2: float
    contacts: list[int] = field(default_factory=list)

    def at(self, day: int) -> float:
        return self.p1 + (self.p2 - self.p1) * (day - self.i1) / (self.i2 - self.i1)


def touch_bucket(count: int) -> str:
    return "touches_4+" if count >= 4 else f"touches_{count}"


def lines(found: Sequence[Pivot]) -> list[tuple[int, Line]]:
    """(élesedés napja, vonal) minden szomszédos pivotpárra, ami emelkedő völgy vagy csökkenő csúcs."""
    out: list[tuple[int, Line]] = []
    for kind, up in (("low", True), ("high", False)):
        seq = sorted((p for p in found if p.kind == kind), key=lambda x: x.index)
        for a, b in pairwise(seq):
            if (up and b.price > a.price) or (not up and b.price < a.price):
                out.append((b.known_at, Line(up, a.index, a.price, b.index, b.price, [a.index, b.index])))
    return out


def events(frame: pd.DataFrame, found: Sequence[Pivot] | None = None) -> list[tuple[int, str, str, str]]:
    """(napindex, szabály, bontás, irány) a vonaltörésekre."""
    low = frame["low"].to_numpy(dtype="float64")
    high = frame["high"].to_numpy(dtype="float64")
    close = frame["close"].to_numpy(dtype="float64")
    band = atr(frame)
    starting: dict[int, list[Line]] = {}
    for day, line in lines(found if found is not None else pivots(frame)):
        starting.setdefault(day, []).append(line)

    active: list[Line] = []
    out: list[tuple[int, str, str, str]] = []
    for t in range(len(close)):
        active.extend(starting.get(t, []))
        if not active:
            continue
        # Lejárat: a második pivot után egy évvel a vonal már nem ugyanaz a vonal.
        active = [ln for ln in active if t - ln.i2 <= LIFETIME]
        if not np.isfinite(band[t]) or band[t] <= 0:
            continue
        keep: list[Line] = []
        for ln in active:
            value = ln.at(t)
            if ln.up and close[t] < value - BREAK_ATR * band[t]:
                out.append((t, "trendline_up_break", touch_bucket(len(ln.contacts)), "short"))
                continue
            if not ln.up and close[t] > value + BREAK_ATR * band[t]:
                out.append((t, "trendline_down_break", touch_bucket(len(ln.contacts)), "long"))
                continue
            near = abs(low[t] - value) if ln.up else abs(high[t] - value)
            on_side = close[t] > value if ln.up else close[t] < value
            if near <= TOUCH_TOLERANCE * band[t] and on_side and t - ln.contacts[-1] >= COOLDOWN:
                ln.contacts.append(t)
            keep.append(ln)
        active = keep
    return out
