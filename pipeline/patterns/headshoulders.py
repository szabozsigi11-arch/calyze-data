"""M3 — Váll-fej-váll és fordítottja (`docs/minta-definiciok.md`, 4. fejezet).

A négy érvényességi állapot mindegyike külön esemény, saját felismerési
nappal: `forming`, `broken`, `retested`, `failed`.

A csapda, amit itt kerülni kell: egy állapot napja nem lehet korábbi annál a
napnál, amikor maga a minta felismerhető lett (a jobb váll pivotjának
felismerése, `P₃ + 5`). Ha a nyakvonal azelőtt tört át, hogy a jobb vállat
láthattuk volna, akkor az áttörés napján a minta még nem is létezett — az
esemény napja ilyenkor a felismerés napja. Ezért minden esemény napja:
`max(az esemény napja, a minta felismerésének napja)`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pipeline.patterns.common import K, Pivot, atr, pivots

#: Ennyi napon belül kell áttörnie a nyakvonalnak, különben a minta elbukott.
BREAK_WINDOW = 40
#: Az áttörés után ennyi napon belül kell a visszatesztnek megtörténnie.
RETEST_WINDOW = 20
#: A visszateszt tűrése ATR-ben.
RETEST_TOLERANCE = 0.5
#: A vállak hasonlósága: |P₁ − P₃| ≤ ennyi · (fej − nyakvonal).
SHOULDER_SYMMETRY = 0.5
#: Az előzetes trend ablaka a bal váll előtt.
PRIOR_WINDOW = 20

STATES = ("forming", "broken", "retested", "failed")


@dataclass(frozen=True)
class Shape:
    """Egy felismert váll-fej-váll: a három pivot, a nyakvonal és az irány."""

    top: bool  # tető (True) vagy fordított, alj (False)
    shoulders: tuple[Pivot, Pivot, Pivot]
    #: a nyakvonal két pontja: (napindex, ár)
    neck: tuple[tuple[int, float], tuple[int, float]]

    @property
    def known_at(self) -> int:
        return self.shoulders[2].known_at

    def neckline(self, day: int) -> float:
        (i1, p1), (i2, p2) = self.neck
        return p1 + (p2 - p1) * (day - i1) / (i2 - i1)


def find_shapes(frame: pd.DataFrame) -> list[Shape]:
    """A papír összes váll-fej-váll alakzata (tető és alj), a definíció szerint."""
    high = frame["high"].to_numpy(dtype="float64")
    low = frame["low"].to_numpy(dtype="float64")
    close = frame["close"].to_numpy(dtype="float64")
    found: list[Shape] = []
    all_pivots = pivots(frame)

    for top in (True, False):
        seq = [p for p in all_pivots if p.kind == ("high" if top else "low")]
        for a, b, c in zip(seq, seq[1:], seq[2:], strict=False):
            if b.index - a.index < 2 or c.index - b.index < 2:
                continue
            # A két völgy (tetőnél) vagy csúcs (aljnál) a pivotok között.
            if top:
                i1 = a.index + 1 + int(np.argmin(low[a.index + 1 : b.index]))
                i2 = b.index + 1 + int(np.argmin(low[b.index + 1 : c.index]))
                n1, n2 = low[i1], low[i2]
                head_ok = b.price > a.price and b.price > c.price
                depth = b.price - max(n1, n2)
            else:
                i1 = a.index + 1 + int(np.argmax(high[a.index + 1 : b.index]))
                i2 = b.index + 1 + int(np.argmax(high[b.index + 1 : c.index]))
                n1, n2 = high[i1], high[i2]
                head_ok = b.price < a.price and b.price < c.price
                depth = min(n1, n2) - b.price
            if not head_ok or depth <= 0:
                continue
            if abs(a.price - c.price) > SHOULDER_SYMMETRY * depth:
                continue
            # Előzetes trend a bal váll előtt: tetőnél emelkedés, aljnál esés.
            start = a.index - PRIOR_WINDOW - 1
            if start < 0:
                continue
            prior = close[a.index - 1] / close[start] - 1
            if (top and prior <= 0) or (not top and prior >= 0):
                continue
            found.append(Shape(top, (a, b, c), ((i1, float(n1)), (i2, float(n2)))))
    return found


def shape_events(shape: Shape, frame: pd.DataFrame) -> list[tuple[int, str, str]]:
    """Egy alakzat állapot-eseményei: (napindex, állapot, irány).

    Minden nap `max(esemény, felismerés)` — a minta nem lehet érvényes
    azelőtt, hogy egyáltalán látható lett volna.
    """
    n = len(frame)
    high = frame["high"].to_numpy(dtype="float64")
    low = frame["low"].to_numpy(dtype="float64")
    close = frame["close"].to_numpy(dtype="float64")
    band = atr(frame)
    p3 = shape.shoulders[2].index
    head = shape.shoulders[1].price
    seen = shape.known_at
    if seen >= n:
        return []

    along = "short" if shape.top else "long"
    against = "long" if shape.top else "short"

    def crossed(day: int) -> bool:
        line = shape.neckline(day)
        return close[day] < line if shape.top else close[day] > line

    def beyond_head(day: int) -> bool:
        return close[day] > head if shape.top else close[day] < head

    out: list[tuple[int, str, str]] = []
    broken = None
    failed = None
    for d in range(p3 + 1, min(p3 + BREAK_WINDOW + 1, n)):
        if beyond_head(d):
            failed = d
            break
        if crossed(d):
            broken = d
            break
    if broken is None and failed is None and p3 + BREAK_WINDOW < n:
        failed = p3 + BREAK_WINDOW

    # forming: csak ha a felismerés napjáig a nyakvonal ép maradt.
    if broken is None or broken > seen:
        if failed is None or failed > seen:
            out.append((seen, "forming", along))

    if broken is not None:
        out.append((max(broken, seen), "broken", along))
        for r in range(broken + 1, min(broken + RETEST_WINDOW + 1, n)):
            tol = band[r] * RETEST_TOLERANCE
            if not np.isfinite(tol):
                continue
            line = shape.neckline(r)
            if shape.top:
                touched = high[r] >= line - tol and close[r] < line
            else:
                touched = low[r] <= line + tol and close[r] > line
            if touched:
                out.append((max(r, seen), "retested", along))
                break
    elif failed is not None:
        out.append((max(failed, seen), "failed", against))
    return out


def events(frame: pd.DataFrame) -> list[tuple[int, str, str, str]]:
    """A papír összes váll-fej-váll eseménye: (napindex, minta, állapot, irány)."""
    out: list[tuple[int, str, str, str]] = []
    for shape in find_shapes(frame):
        name = "hs_top" if shape.top else "hs_bottom"
        for day, state, direction in shape_events(shape, frame):
            out.append((day, name, state, direction))
    # Ugyanaz a minta ugyanabban az állapotban 5 napon belül csak egyszer.
    out.sort()
    kept: list[tuple[int, str, str, str]] = []
    last: dict[tuple[str, str], int] = {}
    for day, name, state, direction in out:
        if day - last.get((name, state), -K) < K:
            continue
        kept.append((day, name, state, direction))
        last[(name, state)] = day
    return kept
