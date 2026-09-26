"""A minta-detektorok közös alapjai (`docs/minta-definiciok.md`, 1. fejezet).

A legfontosabb itt a pivot: egy nap akkor csúcs, ha a körülötte lévő `K`
napon belül a legmagasabb. Ezt csak `K` nappal később lehet tudni. A pivot
ezért két dátumot hordoz — a csúcs napját és a **felismerés** napját —, és a
detektorok kizárólag az utóbbit használhatják eseménynapnak.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

#: A pivot-ablak fél szélessége (a dokumentum szerint 5, és nem mozog).
K = 5
#: Az ATR ablaka (Wilder).
ATR_N = 14
#: Az előzetes trend ablaka.
TREND_N = 10


@dataclass(frozen=True)
class Pivot:
    kind: str  # "high" vagy "low"
    index: int  # a csúcs/völgy napjának indexe
    price: float
    #: az a nap (index), amikor a pivot felismerhetővé vált: `index + K`
    known_at: int


def atr(frame: pd.DataFrame, n: int = ATR_N) -> np.ndarray:
    """Wilder-féle ATR a `t−1` napig — a `t` napi gyertya nem számít bele.

    A tolerancia így csak a már ismert múltból jön; egy nagy mai gyertya nem
    tágíthatja utólag a saját mintájának a kritériumát.
    """
    h = frame["high"].to_numpy(dtype="float64")
    lo = frame["low"].to_numpy(dtype="float64")
    c = frame["close"].to_numpy(dtype="float64")
    prev_close = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - prev_close), np.abs(lo - prev_close)]), axis=0)
    tr[0] = h[0] - lo[0]
    out = pd.Series(tr).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy()
    # Eltolás egy nappal: a `t` napi érték a `t−1`-ig ismert adatból.
    return np.concatenate([[np.nan], out[:-1]])


def prior_trend(frame: pd.DataFrame, n: int = TREND_N) -> np.ndarray:
    """A minta előtti `n` napos hozam: `c[t−1] / c[t−n−1] − 1`."""
    c = frame["close"].to_numpy(dtype="float64")
    out = np.full(len(c), np.nan)
    out[n + 1 :] = c[n:-1] / c[: -n - 1] - 1
    return out


def pivots(frame: pd.DataFrame, k: int = K) -> list[Pivot]:
    """Csúcsok és völgyek, a felismerésük napjával.

    Döntetlennél (két azonos csúcs az ablakban) az első számít, hogy egy
    lapos tető ne adjon két pivotot.
    """
    h = frame["high"].to_numpy(dtype="float64")
    lo = frame["low"].to_numpy(dtype="float64")
    out: list[Pivot] = []
    for p in range(k, len(frame) - k):
        window_h = h[p - k : p + k + 1]
        window_l = lo[p - k : p + k + 1]
        if h[p] == window_h.max() and int(np.argmax(window_h)) == k:
            out.append(Pivot("high", p, float(h[p]), p + k))
        if lo[p] == window_l.min() and int(np.argmin(window_l)) == k:
            out.append(Pivot("low", p, float(lo[p]), p + k))
    return out
