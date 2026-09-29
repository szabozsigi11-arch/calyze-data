"""M4 — Top-down: havi, heti és napi szerkezet egyezése (`docs/minta-definiciok-2.md`, 4. fejezet).

A csapda itt a félkész gyertya: a hét közepén a „heti gyertya” még nem létezik.
Ezért a heti és a havi pivot csak akkor használható, amikor a felismeréséhez
szükséges utolsó gyertya LEZÁRULT — a lezárás utáni első kereskedési naptól.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.patterns.common import Pivot, pivots
from pipeline.patterns.structure import trend_state

#: A heti és a havi pivot ablaka (gyertyában).
HTF_K = 2


def _bars(frame: pd.DataFrame, period: str) -> tuple[pd.DataFrame, np.ndarray]:
    """Magasabb idősíkú gyertyák, és mindegyikhez az utolsó napi indexe."""
    dates = pd.to_datetime(frame["date"]).reset_index(drop=True)
    key = dates.dt.to_period(period)
    data = frame.reset_index(drop=True).assign(_key=key.to_numpy(), _i=np.arange(len(frame)))
    grouped = data.groupby("_key", sort=True)
    bars = pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
        }
    ).reset_index(drop=True)
    last_index = grouped["_i"].max().to_numpy()
    return bars, last_index


def _usable_from(found: list[Pivot], last_index: np.ndarray) -> dict[int, list[Pivot]]:
    """Napi index → az AZON a napon használhatóvá vált magasabb idősíkú pivotok."""
    out: dict[int, list[Pivot]] = {}
    for p in found:
        if p.known_at >= len(last_index):
            continue
        # a felismerő gyertya lezárása utáni első nap
        out.setdefault(int(last_index[p.known_at]) + 1, []).append(p)
    return out


class _State:
    """Egy idősík szerkezete napról napra, ahogy a pivotjai ismertté válnak."""

    def __init__(self, usable: dict[int, list[Pivot]]) -> None:
        self.usable = usable
        self.highs: list[float] = []
        self.lows: list[float] = []

    def advance(self, t: int) -> str:
        for p in sorted(self.usable.get(t, []), key=lambda x: x.index):
            (self.highs if p.kind == "high" else self.lows).append(p.price)
        return trend_state(self.highs, self.lows)


def events(frame: pd.DataFrame, daily: list[Pivot] | None = None) -> list[tuple[int, str, str, str]]:
    """(napindex, szabály, bontás, irány) az egyezés első napjaira. Bontás: "" (nincs), ext_low, ext_high."""
    close = frame["close"].to_numpy(dtype="float64")
    n = len(close)
    weekly, weekly_last = _bars(frame, "W-FRI")
    monthly, monthly_last = _bars(frame, "M")

    daily_found = daily if daily is not None else pivots(frame)
    day_usable: dict[int, list[Pivot]] = {}
    for p in daily_found:
        day_usable.setdefault(p.known_at, []).append(p)

    states = {
        "d": _State(day_usable),
        "w": _State(_usable_from(pivots(weekly, HTF_K), weekly_last)),
        "m": _State(_usable_from(pivots(monthly, HTF_K), monthly_last)),
    }
    previous = "none"
    out: list[tuple[int, str, str, str]] = []
    for t in range(n):
        s = {k: st.advance(t) for k, st in states.items()}
        aligned = s["d"] if s["d"] != "neutral" and s["d"] == s["w"] == s["m"] else "none"
        if aligned != "none" and aligned != previous:
            up = aligned == "up"
            name, direction = ("topdown_up", "long") if up else ("topdown_down", "short")
            highs, lows = states["d"].highs, states["d"].lows
            variant = ""
            if highs and lows and highs[-1] > lows[-1]:
                span = highs[-1] - lows[-1]
                e = (close[t] - lows[-1]) / span if up else (highs[-1] - close[t]) / span
                variant = "ext_low" if e <= 0.5 else "ext_high"
            out.append((t, name, variant, direction))
        previous = aligned
    return out


def alignment_states(frame: pd.DataFrame, daily: list[Pivot] | None = None) -> list[str]:
    """Minden napra: "up", ha mindhárom idősík emelkedő, "down", ha mindhárom csökkenő, egyébként "none".

    Ugyanaz a szabály, mint az eseményeknél (`events`); a konfluencia-motor
    kontextusa ez.
    """
    weekly, weekly_last = _bars(frame, "W-FRI")
    monthly, monthly_last = _bars(frame, "M")
    day_usable: dict[int, list[Pivot]] = {}
    for p in daily if daily is not None else pivots(frame):
        day_usable.setdefault(p.known_at, []).append(p)
    states = (
        _State(day_usable),
        _State(_usable_from(pivots(weekly, HTF_K), weekly_last)),
        _State(_usable_from(pivots(monthly, HTF_K), monthly_last)),
    )
    out: list[str] = []
    for t in range(len(frame)):
        d, w, m = (st.advance(t) for st in states)
        out.append(d if d != "neutral" and d == w == m else "none")
    return out
