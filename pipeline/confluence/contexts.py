"""A konfluencia kiváltói és kontextusai (`docs/konfluencia.md`, 1. fejezet).

A kontextus egy bitmaszk: a kiváltó napján mely állapotok álltak. Iránnyal
együtt számoljuk — long kiváltónál a „trend” azt jelenti, hogy a záróár az
EMA200 fölött van, short-nál azt, hogy alatta —, ezért minden napra két maszk
van, és a kiváltó iránya választ közülük.

Minden állapot csak az aznap ismert adatból áll: az EMA és a forgalmi medián
a mai napig, a pivotok a felismerésük napjától, a szintek a bejárásból.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from itertools import combinations

import numpy as np
import pandas as pd

from pipeline.arena.signals import DIRECTIONS
from pipeline.patterns.common import Pivot
from pipeline.patterns.levels import LevelWalk
from pipeline.patterns.structure import daily_states
from pipeline.patterns.topdown import alignment_states

#: A kontextusok, a dokumentum sorrendjében. A kombináció azonosítója is ebben a sorrendben áll.
CONTEXTS: tuple[str, ...] = ("trend", "level", "structure", "htf", "calm", "volume")
BIT: dict[str, int] = {name: 1 << i for i, name in enumerate(CONTEXTS)}
#: Egy kombinációban legfeljebb ennyi kontextus (a kiváltóval együtt 4 feltétel).
MAX_CONTEXTS = 3
#: A forgalmi feltétel: legalább ennyiszerese a 20 napos mediánnak.
VOLUME_MULTIPLE = 2.0


def is_trigger(rule: str) -> bool:
    """A minta-aréna szabályai közül melyik kiváltó (1. fejezet)."""
    if rule.startswith("hs_"):
        return True  # a négy állapot × tető/alj maga a szabály
    if rule.startswith("fib_"):
        return rule.endswith("|wick")  # a négy változatból csak egy, különben négyszer számítana
    return "|" not in rule  # minden más: az összesített szabály, a bontás nem kiváltó


def excluded(trigger: str) -> frozenset[str]:
    """Kontextusok, amik a kiváltóval önmagukat mérnék (1. fejezet, utolsó bekezdés)."""
    out: set[str] = set()
    if trigger.startswith("sr_") or _is_candle(trigger):
        out.add("level")
    if trigger.startswith("topdown_"):
        out.add("htf")
    if trigger in {"close_above_ema200", "close_below_ema200"}:
        out.add("trend")
    if trigger.startswith("structure_break_"):
        out.add("structure")
    return frozenset(out)


_NOT_CANDLE_PREFIXES = ("hs_", "sr_", "structure_", "breakout_", "fib_", "topdown_", "trendline_")
#: Az indikátor-aréna szabályai (`jelzes-definiciok.md`): nem gyertyaminták.
_INDICATOR_RULES = frozenset(DIRECTIONS)


def _is_candle(rule: str) -> bool:
    return rule not in _INDICATOR_RULES and not rule.startswith(_NOT_CANDLE_PREFIXES)


def subsets(trigger: str) -> list[tuple[str, ...]]:
    """A kiváltóhoz megengedett kontextus-részhalmazok, 1–3 elemmel, a rögzített sorrendben."""
    allowed = [c for c in CONTEXTS if c not in excluded(trigger)]
    return [combo for k in range(1, MAX_CONTEXTS + 1) for combo in combinations(allowed, k)]


def combo_id(trigger: str, contexts: Sequence[str]) -> str:
    return "+".join([trigger, *contexts])


def mask_of(contexts: Sequence[str]) -> int:
    return sum(BIT[c] for c in contexts)


def instrument_masks(
    frame: pd.DataFrame,
    walk: LevelWalk,
    found: Sequence[Pivot],
    regime: Mapping[date, str],
) -> tuple[np.ndarray, np.ndarray]:
    """(long maszk, short maszk) naponként, a dátum szerint rendezett OHLCV-ből."""
    close = frame["close"].astype("float64")
    volume = frame["volume"].astype("float64")
    n = len(frame)

    ema200 = close.ewm(span=200, adjust=False, min_periods=200).mean()
    above = (close > ema200).to_numpy()
    below = (close < ema200).to_numpy()

    structure = np.array(daily_states(frame, found))
    htf = np.array(alignment_states(frame, list(found)))

    days = pd.to_datetime(frame["date"]).dt.date
    # Ahol nincs rezsim-címke, ott nem mondjuk, hogy nyugodt.
    calm = np.array([regime.get(d) not in (None, "stressed") for d in days], dtype=bool)

    median = volume.rolling(20).median()
    heavy = (volume >= VOLUME_MULTIPLE * median).fillna(False).to_numpy(dtype=bool)

    long_mask = np.zeros(n, dtype=np.int64)
    short_mask = np.zeros(n, dtype=np.int64)
    long_mask |= np.where(above, BIT["trend"], 0)
    short_mask |= np.where(below, BIT["trend"], 0)
    long_mask |= np.where(walk.near_support, BIT["level"], 0)
    short_mask |= np.where(walk.near_resistance, BIT["level"], 0)
    long_mask |= np.where(structure == "up", BIT["structure"], 0)
    short_mask |= np.where(structure == "down", BIT["structure"], 0)
    long_mask |= np.where(htf == "up", BIT["htf"], 0)
    short_mask |= np.where(htf == "down", BIT["htf"], 0)
    both = np.where(calm, BIT["calm"], 0) | np.where(heavy, BIT["volume"], 0)
    return long_mask | both, short_mask | both
