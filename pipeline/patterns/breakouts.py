"""M6 — Kitörés és visszateszt (`docs/minta-definiciok-2.md`, 2. fejezet).

A kitörés az M7 szint lejárata: ugyanaz az esemény, két néven. A kitörés utáni
20 napban a visszateszt vagy a hamis kitörés közül legfeljebb egy — amelyik
előbb jön — kap eseményt, a saját napján.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.patterns.common import atr
from pipeline.patterns.levels import LevelWalk

#: Ennyi napon belül kell a visszatesztnek vagy a bukásnak bekövetkeznie.
FOLLOW_WINDOW = 20
#: A visszateszt tűrése ATR-ben (ugyanaz, mint az M7 érintésénél).
RETEST_TOLERANCE = 0.5


def events(frame: pd.DataFrame, walk: LevelWalk) -> list[tuple[int, str, str]]:
    """(napindex, szabály, irány) a kitörésekre és a folytatásukra."""
    low = frame["low"].to_numpy(dtype="float64")
    high = frame["high"].to_numpy(dtype="float64")
    close = frame["close"].to_numpy(dtype="float64")
    band = atr(frame)
    n = len(close)
    out: list[tuple[int, str, str]] = []

    for day, kind, level in walk.breaks:
        up = kind == "resistance"
        name = "breakout_up" if up else "breakout_down"
        out.append((day, name, "long" if up else "short"))
        for t in range(day + 1, min(day + 1 + FOLLOW_WINDOW, n)):
            tol = band[t] * RETEST_TOLERANCE
            if not np.isfinite(tol):
                continue
            if up:
                if close[t] < level:
                    out.append((t, "breakout_up_failed", "short"))
                    break
                if close[t] > level and abs(low[t] - level) <= tol:
                    out.append((t, "breakout_up_retest", "long"))
                    break
            else:
                if close[t] > level:
                    out.append((t, "breakout_down_failed", "long"))
                    break
                if close[t] < level and abs(high[t] - level) <= tol:
                    out.append((t, "breakout_down_retest", "short"))
                    break
    return out
