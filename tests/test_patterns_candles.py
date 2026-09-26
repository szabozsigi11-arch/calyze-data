"""M2: a gyertyaminták pontosan a definíciós dokumentum szabályai szerint."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from pipeline.patterns.candles import LOW_RELIABILITY, PATTERNS, SYNONYMS, detect, events
from pipeline.patterns.levels import walk_levels

DOC = "docs/minta-definiciok.md"


def candles(rows: list[tuple[float, float, float, float]], lead: str = "down") -> pd.DataFrame:
    """Előzetes trend (12 nap), utána a megadott gyertyák (o, h, l, c)."""
    step = -1.0 if lead == "down" else 1.0
    start = 130.0 if lead == "down" else 70.0
    pre = [(start + i * step,) * 4 for i in range(12)]
    data = [(p[0], p[0] + 0.2, p[0] - 0.2, p[0]) for p in pre] + rows
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(len(data))]
    o, h, lo, c = zip(*data, strict=True)
    return pd.DataFrame({"date": days, "open": o, "high": h, "low": lo, "close": c, "volume": 1e6})


def fired_on_last(frame: pd.DataFrame, name: str) -> bool:
    return bool(detect(frame)[name][-1])


def test_minden_minta_es_szinonima_szerepel_a_dokumentumban() -> None:
    text = open(DOC, encoding="utf-8").read()
    for name in PATTERNS:
        assert f"`{name}`" in text, name
    for alias, canonical in SYNONYMS.items():
        assert alias in text, alias
        assert canonical in PATTERNS, f"{alias} → {canonical} nem létező minta"


def test_a_szinonima_nem_kulon_minta() -> None:
    """A szótár nevei nem detektálódnak külön — egyszer mérjük őket."""
    for alias in SYNONYMS:
        assert alias.replace(" ", "_") not in PATTERNS


def test_kalapacs_eses_utan() -> None:
    # Hosszú alsó árnyék, kis test fent, szinte nincs felső árnyék.
    frame = candles([(118.0, 118.1, 114.0, 118.05)], lead="down")
    assert fired_on_last(frame, "hammer")
    assert not fired_on_last(frame, "hanging_man")


def test_ugyanaz_a_gyertya_emelkedes_utan_akasztott_ember() -> None:
    frame = candles([(82.0, 82.1, 78.0, 82.05)], lead="up")
    assert fired_on_last(frame, "hanging_man")
    assert not fired_on_last(frame, "hammer")


def test_hullocsillag_emelkedes_utan() -> None:
    frame = candles([(82.0, 86.0, 81.95, 82.05)], lead="up")
    assert fired_on_last(frame, "shooting_star")


def test_bullish_engulfing() -> None:
    frame = candles([(119.0, 119.2, 117.8, 118.0), (117.9, 119.6, 117.7, 119.4)], lead="down")
    assert fired_on_last(frame, "bullish_engulfing")


def test_az_engulfing_emelkedes_utan_nem_bullish() -> None:
    frame = candles([(83.0, 83.2, 81.8, 82.0), (81.9, 83.6, 81.7, 83.4)], lead="up")
    assert not fired_on_last(frame, "bullish_engulfing")


def test_hajnalcsillag() -> None:
    frame = candles(
        [
            (119.0, 119.1, 115.9, 116.0),  # hosszú piros
            (115.5, 115.8, 115.0, 115.4),  # kis test, a tegnapi záró alatt
            (115.6, 118.4, 115.5, 118.2),  # zöld, a felezőpont (117,5) fölött zár
        ],
        lead="down",
    )
    assert fired_on_last(frame, "morning_star")
    assert not fired_on_last(frame, "morning_doji_star")


def test_doji_hajnalcsillag_a_hajnalcsillag_resze() -> None:
    frame = candles(
        [(119.0, 119.1, 115.9, 116.0), (115.45, 115.9, 115.0, 115.4), (115.6, 118.4, 115.5, 118.2)],
        lead="down",
    )
    assert fired_on_last(frame, "morning_doji_star")
    assert fired_on_last(frame, "morning_star")


def test_harom_feher_katona() -> None:
    frame = candles(
        [(117.0, 118.1, 116.9, 118.0), (117.5, 119.1, 117.4, 119.0), (118.5, 120.1, 118.4, 120.0)],
        lead="down",
    )
    assert fired_on_last(frame, "three_white_soldiers")


def test_minden_mintanak_van_iranya_es_az_alacsony_megbizhatosagiak_is_mertek() -> None:
    assert {d for d, _ in PATTERNS.values()} == {"long", "short"}
    assert LOW_RELIABILITY <= set(PATTERNS)


def test_a_kontextus_a_szinthez_mer() -> None:
    """Kalapács egy háromszor visszapattant támasznál: at_level. Ugyanaz a
    gyertya a semmi közepén: none."""
    base: list[float] = [110.0] * 30
    for _ in range(3):
        base += list(np.linspace(110, 100.3, 12)) + list(np.linspace(100.3, 110, 12)) + [110.0] * 6
    base += list(np.linspace(110, 102.0, 11))
    rows = [(v, v + 0.5, v - 0.5, v) for v in base]
    # A kalapács mélypontja pont a 100-as támaszon.
    rows.append((101.9, 102.0, 100.2, 101.95))
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(len(rows))]
    o, h, lo, c = zip(*rows, strict=True)
    frame = pd.DataFrame({"date": days, "open": o, "high": h, "low": lo, "close": c, "volume": 1e6})

    found = [e for e in events(frame, walk_levels(frame)) if e[1] == "hammer" and e[0] == len(rows) - 1]
    assert found, "a kalapácsnak meg kell lennie"
    assert found[0][2] == "at_level"
