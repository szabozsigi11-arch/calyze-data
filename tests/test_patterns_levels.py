"""M7: a szintek csak attól a naptól léteznek, amikor felismerhetők voltak."""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise

import numpy as np
import pandas as pd

from pipeline.patterns.common import K, atr, pivots, prior_trend
from pipeline.patterns.levels import COOLDOWN, touch_bucket, walk_levels


def frame_from(closes: list[float], spread: float = 0.5) -> pd.DataFrame:
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(len(closes))]
    c = np.array(closes)
    return pd.DataFrame(
        {"date": days, "open": c, "high": c + spread, "low": c - spread, "close": c, "volume": 1e6}
    )


def bounce_series() -> list[float]:
    """Egy papír, ami háromszor visszapattan ugyanarról a 100-as szintről."""
    out: list[float] = [110.0] * 30
    for _ in range(4):
        out += list(np.linspace(110, 100.3, 12)) + list(np.linspace(100.3, 110, 12)) + [110.0] * 6
    return out


def test_a_pivot_csak_k_nappal_kesobb_ismerheto_fel() -> None:
    f = frame_from(bounce_series())
    for p in pivots(f):
        assert p.known_at == p.index + K


def test_az_atr_nem_latja_a_mai_gyertyat() -> None:
    """A tűrés csak a múltból jöhet: egy nagy mai gyertya nem tágíthatja."""
    closes = [100.0] * 40
    quiet = atr(frame_from(closes))
    loud = frame_from(closes)
    loud.loc[39, "high"] = 200.0
    assert atr(loud)[39] == quiet[39]


def test_az_elozetes_trend_a_minta_elotti_napig_tart() -> None:
    closes = [float(i) for i in range(1, 30)]
    trend = prior_trend(frame_from(closes))
    # A t-edik napon: c[t−1] / c[t−11] − 1 — a mai záró nem számít bele.
    assert trend[20] == closes[19] / closes[9] - 1


def test_a_szint_masodik_pivotja_elott_nincs_erintes() -> None:
    f = frame_from(bounce_series())
    walk = walk_levels(f)
    lows = [p for p in pivots(f) if p.kind == "low"]
    assert len(lows) >= 2
    born = lows[1].known_at
    assert walk.touches, "a harmadik visszapattanásnak érintésnek kell lennie"
    assert all(day >= born for day, *_ in walk.touches)


def test_az_elso_erintes_a_harmadik_talalkozas() -> None:
    walk = walk_levels(frame_from(bounce_series()))
    supports = [t for t in walk.touches if t[1] == "sr_support_touch"]
    assert supports[0][2] == 3
    assert touch_bucket(3) == "3"
    assert touch_bucket(7) == "5+"


def test_ket_erintes_kozott_legalabb_cooldown_nap_van() -> None:
    walk = walk_levels(frame_from(bounce_series()))
    days = [t[0] for t in walk.touches if t[1] == "sr_support_touch"]
    assert all(b - a >= COOLDOWN for a, b in pairwise(days))


def test_a_szint_lejar_ha_az_ar_athalad_rajta() -> None:
    """Támasz alatti zárás után a szint nem érinthető."""
    closes = bounce_series() + list(np.linspace(110, 80, 20)) + [80.0] * 20 + list(np.linspace(80, 100, 15))
    walk = walk_levels(frame_from(closes))
    breakdown = len(bounce_series()) + 20
    later = [t for t in walk.touches if t[1] == "sr_support_touch" and t[0] > breakdown]
    assert later == [], "a letört támasz nem ad érintést"
