"""M3: a négy állapot külön esemény, és egyik sem korábbi a minta felismerésénél."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from pipeline.patterns.headshoulders import events, find_shapes, shape_events


def path(*segments: tuple[float, float, int]) -> list[float]:
    out: list[float] = []
    for start, end, steps in segments:
        out += list(np.linspace(start, end, steps, endpoint=False))
    return out


def frame(closes: list[float]) -> pd.DataFrame:
    c = np.array(closes)
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(len(c))]
    return pd.DataFrame({"date": days, "open": c, "high": c + 0.3, "low": c - 0.3, "close": c, "volume": 1e6})


# Emelkedés → bal váll (110) → völgy (100) → fej (120) → völgy (100) → jobb váll (110)
BODY = path(
    (80, 100, 30),
    (100, 110, 10),
    (110, 100, 10),
    (100, 120, 10),
    (120, 100, 10),
    (100, 110, 10),
    (110, 104, 8),
)


def classic() -> pd.DataFrame:
    # … lassú esés a nyakvonal alá, visszateszt a 100-as szintig, majd tovább le.
    return frame(BODY + path((104, 96, 8), (96, 99.9, 6), (99.9, 85, 20)) + [85.0] * 30)


def test_a_klasszikus_tetot_megtalalja() -> None:
    shapes = find_shapes(classic())
    tops = [s for s in shapes if s.top]
    assert len(tops) == 1
    left, head, right = tops[0].shoulders
    assert head.price > left.price
    assert head.price > right.price


def test_formingtol_a_visszatesztig_sorrendben() -> None:
    f = classic()
    shape = next(s for s in find_shapes(f) if s.top)
    states = [state for _, state, _ in shape_events(shape, f)]
    assert states == ["forming", "broken", "retested"]


def test_egyik_allapot_sem_korabbi_a_felismeresnel() -> None:
    f = classic()
    for shape in find_shapes(f):
        for day, _, _ in shape_events(shape, f):
            assert day >= shape.known_at


def test_a_teto_iranya_short_a_bukase_long() -> None:
    # A jobb váll után az ár a fej fölé megy: a tető elbukott.
    f = frame(BODY + path((104, 125, 15)) + [125.0] * 50)
    shape = next(s for s in find_shapes(f) if s.top)
    result = shape_events(shape, f)
    assert [(s, d) for _, s, d in result if s == "failed"] == [("failed", "long")]
    assert all(s != "broken" for _, s, _ in result)


def test_ha_a_felismeres_elott_tort_at_nincs_forming() -> None:
    """A nyakvonal áttörése a jobb váll felismerése ELŐTT: akkor a minta még
    nem látszott. Nincs forming, az áttörés napja pedig a felismerés napja."""
    early = frame(
        path((80, 100, 30), (100, 110, 10), (110, 100, 10), (100, 120, 10), (120, 100, 10), (100, 110, 10))
        + path((110, 90, 4), (90, 80, 20))
        + [80.0] * 40
    )
    tops = [s for s in find_shapes(early) if s.top]
    # Nincs menekülőút: ha az alakzat nem található, a teszt nem azt vizsgálja,
    # amire írtuk — azt hangosan kell jeleznie, nem csendben átmennie.
    assert len(tops) == 1
    shape = tops[0]
    result = shape_events(shape, early)
    assert "forming" not in [s for _, s, _ in result]
    broken = [d for d, s, _ in result if s == "broken"]
    assert broken == [shape.known_at]


def test_az_esemenyek_nevvel_es_irannyal_jonnek() -> None:
    out = events(classic())
    assert out
    for _, name, state, direction in out:
        assert name in {"hs_top", "hs_bottom"}
        assert state in {"forming", "broken", "retested", "failed"}
        assert direction in {"long", "short"}
