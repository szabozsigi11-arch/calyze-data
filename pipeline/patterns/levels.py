"""M7 — Támasz és ellenállás (`docs/minta-definiciok.md`, 2. fejezet).

A papír napjain időrendben haladunk, és minden napon csak azt használjuk,
ami AZNAP ismert volt: a pivotot a felismerése napjától, a szintet a második
pivotja felismerésétől, az ATR-t a tegnapig. A bejárás ezért lassabb egy
vektoros számításnál — cserébe nem tud a jövőbe nézni.

A bejárás két dolgot ad vissza:
  - az érintés-eseményeket (a mérésnek),
  - naponként, hogy a mélypont élő támasznál, a csúcs élő ellenállásnál volt-e
    (a gyertyaminták kontextusának).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pipeline.patterns.common import atr, pivots

#: A csoportosítás és az érintés tűrése ATR-ben.
TOLERANCE = 0.5
#: A szint lejár, ha a záróár ennyi ATR-rel átlépi.
EXPIRY = 1.0
#: Két érintés akkor külön, ha legalább ennyi nap van köztük (ez az
#: ismétlődés-zár is).
COOLDOWN = 5
#: Friss a szint, ha az előző érintés ennyi napon belül volt.
FRESH = 60
#: Egy magányos pivot ennyi nap után kiesik, ha nem kapott társat — egy év
#: múltán már nem „ugyanaz a szint”, és a lista különben végtelenül nőne.
PENDING_DAYS = 252


@dataclass
class Level:
    kind: str  # "support" vagy "resistance"
    prices: list[float] = field(default_factory=list)
    #: a találkozások napjai (pivotok és érintések) — ebből jön az érintésszám
    contacts: list[int] = field(default_factory=list)
    alive: bool = True

    @property
    def price(self) -> float:
        return float(np.mean(self.prices))

    @property
    def live(self) -> bool:
        # Egy szint két pivottól él.
        return self.alive and len(self.prices) >= 2

    def add_contact(self, day: int) -> bool:
        """Új találkozás. Hamis, ha az utolsótól 5 napon belül van (ugyanaz)."""
        if self.contacts and day - self.contacts[-1] < COOLDOWN:
            return False
        self.contacts.append(day)
        return True


@dataclass
class LevelWalk:
    #: érintés-események: (napindex, szabály, érintés-sorszám, friss-e)
    touches: list[tuple[int, str, int, bool]]
    #: naponként: a mélypont élő támasztól TOLERANCE·ATR-en belül volt-e
    near_support: np.ndarray
    #: naponként: a csúcs élő ellenállástól TOLERANCE·ATR-en belül volt-e
    near_resistance: np.ndarray
    #: naponként az élő támaszok és ellenállások ára, és a napi tűrés — a
    #: többgyertyás minták kontextusához, ahol a minta mélypontja nem
    #: feltétlenül az utolsó napon van
    supports: list[tuple[float, ...]]
    resistances: list[tuple[float, ...]]
    tolerance: np.ndarray

    def at_support(self, day: int, price: float) -> bool:
        tol = self.tolerance[day]
        return bool(np.isfinite(tol)) and any(abs(price - s) <= tol for s in self.supports[day])

    def at_resistance(self, day: int, price: float) -> bool:
        tol = self.tolerance[day]
        return bool(np.isfinite(tol)) and any(abs(price - r) <= tol for r in self.resistances[day])


def walk_levels(frame: pd.DataFrame) -> LevelWalk:
    """Egy papír szintjei és érintései, időrendben, a jövő ismerete nélkül."""
    n = len(frame)
    high = frame["high"].to_numpy(dtype="float64")
    low = frame["low"].to_numpy(dtype="float64")
    close = frame["close"].to_numpy(dtype="float64")
    band = atr(frame)

    by_day: dict[int, list] = {}
    for p in pivots(frame):
        by_day.setdefault(p.known_at, []).append(p)

    levels: list[Level] = []
    touches: list[tuple[int, str, int, bool]] = []
    near_support = np.zeros(n, dtype=bool)
    near_resistance = np.zeros(n, dtype=bool)
    supports: list[tuple[float, ...]] = [() for _ in range(n)]
    resistances: list[tuple[float, ...]] = [() for _ in range(n)]
    tolerance = np.full(n, np.nan)
    last_event = {"support": -COOLDOWN, "resistance": -COOLDOWN}

    for t in range(n):
        tol = band[t] * TOLERANCE if np.isfinite(band[t]) else np.nan
        if not np.isfinite(tol) or tol <= 0:
            continue

        # 0. Gyomlálás: a lejárt szintek és a társ nélkül maradt régi pivotok
        # kiesnek. Enélkül a lista a papír teljes múltjával nőne, és a bejárás
        # 620 papíron milliárdos lépésszámú lenne.
        if t % 20 == 0:
            levels = [lv for lv in levels if lv.alive and (lv.live or t - lv.contacts[-1] <= PENDING_DAYS)]

        # 1. A ma felismerhetővé vált pivotok beépítése.
        for p in by_day.get(t, []):
            kind = "support" if p.kind == "low" else "resistance"
            match = next(
                (lv for lv in levels if lv.alive and lv.kind == kind and abs(lv.price - p.price) <= tol),
                None,
            )
            if match is None:
                levels.append(Level(kind, [p.price], [p.index]))
            elif match.add_contact(p.index):
                match.prices.append(p.price)

        # 2. Lejárat: a záróár EXPIRY·ATR-rel átlépte a szintet.
        for lv in levels:
            if not lv.live:
                continue
            if lv.kind == "support" and close[t] < lv.price - EXPIRY * band[t]:
                lv.alive = False
            elif lv.kind == "resistance" and close[t] > lv.price + EXPIRY * band[t]:
                lv.alive = False

        # 3. A mai nap a szintnél volt-e (a gyertyaminták kontextusa).
        live = [lv for lv in levels if lv.live]
        supports[t] = tuple(lv.price for lv in live if lv.kind == "support")
        resistances[t] = tuple(lv.price for lv in live if lv.kind == "resistance")
        tolerance[t] = tol
        near_support[t] = any(lv.kind == "support" and abs(low[t] - lv.price) <= tol for lv in live)
        near_resistance[t] = any(lv.kind == "resistance" and abs(high[t] - lv.price) <= tol for lv in live)

        # 4. Érintések: a szint közelébe ért, de a záróár a jó oldalon maradt.
        for lv in live:
            if lv.kind == "support":
                touched = abs(low[t] - lv.price) <= tol and close[t] > lv.price
            else:
                touched = abs(high[t] - lv.price) <= tol and close[t] < lv.price
            if not touched or t - last_event[lv.kind] < COOLDOWN:
                continue
            previous = lv.contacts[-1] if lv.contacts else None
            if not lv.add_contact(t):
                continue
            fresh = previous is not None and t - previous <= FRESH
            rule = "sr_support_touch" if lv.kind == "support" else "sr_resistance_touch"
            touches.append((t, rule, len(lv.contacts), fresh))
            last_event[lv.kind] = t

    return LevelWalk(touches, near_support, near_resistance, supports, resistances, tolerance)


def touch_bucket(number: int) -> str:
    """A spec bontása: 3., 4., 5. vagy több (a két alkotó pivot az 1. és a 2.)."""
    return "5+" if number >= 5 else str(number)
