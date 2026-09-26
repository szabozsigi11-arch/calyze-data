"""A piac-implikált baseline számítása (`docs/piac-implikalt-baseline.md`).

Tiszta függvények: egy opciós láncból (táblázat) és a mai árból számolnak, a
lekérés nincs itt. Így a képletek kitalált láncokon tesztelhetők, és a
lekérés hibája nem keveredik a számítás hibájával.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from pipeline.calendar import sessions

#: A célnap és a lejárat közti legnagyobb eltérés kereskedési napban.
EXPIRY_TOLERANCE = {5: 2, 20: 5, 60: 10}
#: A szórás legfeljebb a közép-ár ekkora része lehet.
MAX_SPREAD = 0.25
#: Ennyi nyitott pozíció kell mindkét kötési áron.
MIN_OPEN_INTEREST = 100
#: A valószínűség ezen kívül rossz árat jelez.
PROB_RANGE = (0.01, 0.99)
#: A 90%-os sáv normális kvantilise.
Z90 = 1.6448536269514722


@dataclass(frozen=True)
class Implied:
    status: str  # "ok" vagy a „nem elérhető” oka
    prob_up: float | None = None
    iv: float | None = None
    band_low: float | None = None
    band_high: float | None = None
    expiry: date | None = None


def choose_expiry(expiries: list[date], target: date, horizon: int) -> date | None:
    """A célnaphoz legközelebbi lejárat, ha a tűrésen belül van."""
    best: tuple[int, date] | None = None
    for expiry in expiries:
        lo, hi = sorted((expiry, target))
        gap = max(len(sessions(lo, hi)) - 1, 0)
        if best is None or gap < best[0]:
            best = (gap, expiry)
    if best is None or best[0] > EXPIRY_TOLERANCE[horizon]:
        return None
    return best[1]


def _usable(row: pd.Series) -> bool:
    bid, ask, oi = float(row["bid"]), float(row["ask"]), float(row.get("openInterest") or 0)
    if not (bid > 0 and ask > 0 and ask >= bid):
        return False
    mid = (bid + ask) / 2
    return (ask - bid) / mid <= MAX_SPREAD and oi >= MIN_OPEN_INTEREST


def implied_from_chain(
    calls: pd.DataFrame, spot: float, session: date, expiry: date, rate: float, horizon: int
) -> Implied:
    """A kockázatsemleges emelkedési valószínűség és az implikált sáv.

    Két szomszédos call közép-árából (digitális közelítés): a pár felezőpontja
    a lehető legközelebb a mai árhoz. Az egyetlen volatilitásos képlet a
    valószínűséget 50% köré tenné — az nem a piac véleménye.
    """
    chain = calls.dropna(subset=["strike", "bid", "ask"]).sort_values("strike").reset_index(drop=True)
    if len(chain) < 2:
        return Implied("no_chain")
    strikes = chain["strike"].to_numpy(dtype="float64")
    mids = (strikes[:-1] + strikes[1:]) / 2
    i = int(abs(mids - spot).argmin())
    low, high = chain.iloc[i], chain.iloc[i + 1]
    if not (_usable(low) and _usable(high)):
        return Implied("illiquid", expiry=expiry)

    years = (expiry - session).days / 365
    if years <= 0:
        return Implied("no_expiry")
    c1 = (float(low["bid"]) + float(low["ask"])) / 2
    c2 = (float(high["bid"]) + float(high["ask"])) / 2
    k1, k2 = float(low["strike"]), float(high["strike"])
    prob = -(c2 - c1) / (k2 - k1) * math.exp(rate * years)
    if not (PROB_RANGE[0] <= prob <= PROB_RANGE[1]):
        return Implied("bad_price", expiry=expiry)

    # Implikált volatilitás a mai árra, a két kötési ár között lineárisan.
    v1, v2 = float(low.get("impliedVolatility") or 0), float(high.get("impliedVolatility") or 0)
    weight = min(max((spot - k1) / (k2 - k1), 0.0), 1.0)
    iv = v1 + (v2 - v1) * weight
    band_low = band_high = None
    if 0.01 < iv < 3:
        t = horizon / 252
        drift = (rate - iv * iv / 2) * t
        band_low = drift - Z90 * iv * math.sqrt(t)
        band_high = drift + Z90 * iv * math.sqrt(t)
    return Implied("ok", prob, iv if 0.01 < iv < 3 else None, band_low, band_high, expiry)
