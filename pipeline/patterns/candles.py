"""M2 — Gyertya-fordulómintázatok (`docs/minta-definiciok.md`, 3. fejezet).

Minden szabály pontosan a dokumentum táblázata. Ha itt valami eltér tőle, az
hiba — a dokumentumot nem igazítjuk a kódhoz.

A minta a legutolsó gyertyája napján ismerhető fel, és ez az esemény napja.
Az előzetes trend a minta ELSŐ gyertyája előtti napig tart, a kontextus pedig
a minta szélső pontját (bullishnál a mélypontot, bearishnél a csúcsot) méri
az aznap már élő szintekhez.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.patterns.common import prior_trend
from pipeline.patterns.levels import COOLDOWN, LevelWalk

#: Minden kanonikus minta iránya és gyertyaszáma. A szinonimák nincsenek itt:
#: azokat nem detektáljuk külön (lásd `SYNONYMS`).
PATTERNS: dict[str, tuple[str, int]] = {
    "hammer": ("long", 1),
    "hanging_man": ("short", 1),
    "inverted_hammer": ("long", 1),
    "shooting_star": ("short", 1),
    "bullish_engulfing": ("long", 2),
    "bearish_engulfing": ("short", 2),
    "morning_star": ("long", 3),
    "evening_star": ("short", 3),
    "morning_doji_star": ("long", 3),
    "evening_doji_star": ("short", 3),
    # Alacsony megbízhatóságúak — ezeket is mérjük.
    "piercing_line": ("long", 2),
    "dark_cloud_cover": ("short", 2),
    "bullish_harami": ("long", 2),
    "bearish_harami": ("short", 2),
    "three_white_soldiers": ("long", 3),
    "three_black_crows": ("short", 3),
}

LOW_RELIABILITY = frozenset(
    {
        "piercing_line",
        "dark_cloud_cover",
        "bullish_harami",
        "bearish_harami",
        "three_white_soldiers",
        "three_black_crows",
    }
)

#: A szinonimaszótár (spec/08, 1.1). Ezeket NEM detektáljuk és NEM mérjük
#: külön: egyszer mérjük őket, a kanonikus nevükön. A felület megmutatja.
SYNONYMS: dict[str, str] = {
    "bullish belt hold": "bullish_engulfing",
    "bearish belt hold": "bearish_engulfing",
    "bullish meeting line": "morning_star",
    "bearish meeting line": "evening_star",
    "tower bottom": "morning_star",
    "fry pan bottom": "morning_star",
    "tower top": "evening_star",
    "dumpling top": "evening_star",
    "advanced block": "shooting_star",
    "three stars in the south": "hammer",
}


def _shift(a: np.ndarray, k: int) -> np.ndarray:
    """`a` eltolva `k` nappal: az `i`-edik elem az `i − k`-adik nap értéke."""
    out = np.full(len(a), np.nan)
    if k < len(a):
        out[k:] = a[: len(a) - k]
    return out


def detect(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    """Naponként: melyik minta zárult le aznap. A kontextus itt még nincs."""
    o = frame["open"].to_numpy(dtype="float64")
    h = frame["high"].to_numpy(dtype="float64")
    lo = frame["low"].to_numpy(dtype="float64")
    c = frame["close"].to_numpy(dtype="float64")
    body = np.abs(c - o)
    rng = h - lo
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - lo
    green, red = c > o, c < o
    with np.errstate(invalid="ignore"):
        doji = body <= 0.1 * rng
    trend = prior_trend(frame)

    def back(a: np.ndarray, k: int) -> np.ndarray:
        return _shift(a, k)

    # Az előzetes trend a minta első gyertyája előtti napig.
    trend1, trend2, trend3 = trend, back(trend, 1), back(trend, 2)
    down1, up1 = trend1 < 0, trend1 > 0
    down2, up2 = trend2 < 0, trend2 > 0
    down3, up3 = trend3 < 0, trend3 > 0

    has_range = rng > 0
    with np.errstate(invalid="ignore"):
        hammer_shape = has_range & (lower >= 2 * body) & (upper <= 0.1 * rng) & (body <= 0.3 * rng)
        inverted_shape = has_range & (upper >= 2 * body) & (lower <= 0.1 * rng) & (body <= 0.3 * rng)

    o1, h1, l1, c1 = back(o, 1), back(h, 1), back(lo, 1), back(c, 1)
    b1, r1 = back(body, 1), back(rng, 1)
    green1, red1 = back(green.astype(float), 1) == 1, back(red.astype(float), 1) == 1
    o2, c2 = back(o, 2), back(c, 2)
    b2, r2 = back(body, 2), back(rng, 2)
    green2, red2 = back(green.astype(float), 2) == 1, back(red.astype(float), 2) == 1
    doji1 = back(doji.astype(float), 1) == 1

    with np.errstate(invalid="ignore"):
        mid1 = (o1 + c1) / 2  # a tegnapi test felezőpontja
        mid2 = (o2 + c2) / 2  # a tegnapelőtti test felezőpontja
        long2 = b2 >= 0.6 * r2  # a csillagminták első gyertyája hosszú testű
        long1 = b1 >= 0.6 * r1

        star_small = b1 <= 0.3 * b2
        morning = red2 & long2 & star_small & (np.maximum(o1, c1) < c2) & green & (c > mid2) & down3
        evening = green2 & long2 & star_small & (np.minimum(o1, c1) > c2) & red & (c < mid2) & up3

        body_hi, body_lo = np.maximum(o, c), np.minimum(o, c)
        body1_hi, body1_lo = np.maximum(o1, c1), np.minimum(o1, c1)

        return {
            "hammer": hammer_shape & down1,
            "hanging_man": hammer_shape & up1,
            "inverted_hammer": inverted_shape & down1,
            "shooting_star": inverted_shape & up1,
            "bullish_engulfing": red1 & green & (o <= c1) & (c >= o1) & down2,
            "bearish_engulfing": green1 & red & (o >= c1) & (c <= o1) & up2,
            "morning_star": morning,
            "evening_star": evening,
            "morning_doji_star": morning & doji1,
            "evening_doji_star": evening & doji1,
            "piercing_line": red1 & long1 & green & (o < l1) & (c > mid1) & (c < o1) & down2,
            "dark_cloud_cover": green1 & long1 & red & (o > h1) & (c < mid1) & (c > o1) & up2,
            "bullish_harami": red1 & green & (body_hi <= body1_hi) & (body_lo >= body1_lo) & down2,
            "bearish_harami": green1 & red & (body_hi <= body1_hi) & (body_lo >= body1_lo) & up2,
            "three_white_soldiers": (
                green2
                & green1
                & green
                & (c1 > c2)
                & (c > c1)
                & (o1 >= o2)
                & (o1 <= c2)
                & (o >= o1)
                & (o <= c1)
                & down3
            ),
            "three_black_crows": (
                red2
                & red1
                & red
                & (c1 < c2)
                & (c < c1)
                & (o1 <= o2)
                & (o1 >= c2)
                & (o <= o1)
                & (o >= c1)
                & up3
            ),
        }


def events(frame: pd.DataFrame, walk: LevelWalk) -> list[tuple[int, str, str]]:
    """A papír minta-eseményei: (napindex, minta, kontextus).

    Kontextus: `at_level`, ha a minta szélső pontja az aznap élő szinttől
    tűrésen belül van; különben `none`. A kettő külön mérődik.
    """
    hits = detect(frame)
    lo = frame["low"].to_numpy(dtype="float64")
    h = frame["high"].to_numpy(dtype="float64")
    out: list[tuple[int, str, str]] = []
    for name, mask in hits.items():
        direction, span = PATTERNS[name]
        last = -COOLDOWN
        for t in np.flatnonzero(np.nan_to_num(mask, nan=0).astype(bool)):
            t = int(t)
            if t - last < COOLDOWN:
                continue
            first = t - span + 1
            if direction == "long":
                context = "at_level" if walk.at_support(t, float(lo[first : t + 1].min())) else "none"
            else:
                context = "at_level" if walk.at_resistance(t, float(h[first : t + 1].max())) else "none"
            out.append((t, name, context))
            last = t
    return sorted(out)
