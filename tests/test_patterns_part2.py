"""A 2. rész detektorai (`docs/minta-definiciok-2.md`): M1, M4, M5, M6, M9.

A legfontosabb teszt a jövőbe-nézés tilalma: ha a papír múltját egy napon
elvágjuk, az addigi események pontosan ugyanazok maradnak, mint a teljes
múlton számolva. Ha egy detektor a jövőből is merítene, itt elbukna.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pipeline.patterns import breakouts, fibonacci, structure, topdown, trendlines
from pipeline.patterns.common import lock, pivots
from pipeline.patterns.levels import walk_levels
from pipeline.patterns.run import instrument_events


def path(*segments: tuple[float, float, int]) -> list[float]:
    out: list[float] = []
    for start, end, steps in segments:
        out += list(np.linspace(start, end, steps, endpoint=False))
    return out


def frame(closes: list[float], spread: float = 0.3) -> pd.DataFrame:
    c = np.array(closes, dtype="float64")
    days = [date(2015, 1, 1) + timedelta(days=i) for i in range(len(c))]
    return pd.DataFrame(
        {"date": days, "open": c, "high": c + spread, "low": c - spread, "close": c, "volume": 1e6}
    )


def random_walk(seed: int, n: int = 1400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, n)))
    open_ = close * np.exp(rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.006, n)))
    days = pd.bdate_range("2015-01-01", periods=n).date
    return pd.DataFrame(
        {"date": days, "open": open_, "high": high, "low": low, "close": close, "volume": 1e6}
    )


# ---------------------------------------------------------------- jövőbe-nézés


DETECTORS = {
    "structure": lambda f: structure.events(f),
    "fibonacci": lambda f: fibonacci.events(f),
    "topdown": lambda f: topdown.events(f),
    "trendlines": lambda f: trendlines.events(f),
    "breakouts": lambda f: breakouts.events(f, walk_levels(f)),
}


@pytest.mark.parametrize("name", sorted(DETECTORS))
@pytest.mark.parametrize("seed", [1, 7])
def test_a_multon_elvagva_ugyanazok_az_esemenyek(name: str, seed: int) -> None:
    full = random_walk(seed)
    detect = DETECTORS[name]
    everything = detect(full)
    assert everything, f"{name}: a véletlen bolyongáson egy esemény sem lett — a teszt semmit nem bizonyítana"
    for cut in (500, 900, 1250):
        early = sorted(e for e in detect(full.iloc[:cut].reset_index(drop=True)))
        same = sorted(e for e in everything if e[0] < cut)
        assert early == same, f"{name}: a {cut}. napig mást ad, ha a jövő is látszik"


# ---------------------------------------------------------------- M5


def test_emelkedo_szerkezetben_a_csucs_torese_bos() -> None:
    # emelkedő cikcakk: magasabb csúcsok és magasabb völgyek, majd új csúcs
    f = frame(
        path((100, 110, 10), (110, 104, 10), (104, 116, 10), (116, 109, 10), (109, 125, 12)) + [125.0] * 10
    )
    ups = [e for e in structure.events(f) if e[1] == "structure_break_up"]
    assert ups[-1][2] == "bos"
    assert ups[-1][3] == "long"


def test_csokkeno_szerkezetben_a_csucs_torese_choch() -> None:
    f = frame(
        path((130, 120, 10), (120, 126, 10), (126, 112, 10), (112, 118, 10), (118, 105, 10), (105, 125, 14))
    )
    ups = [e for e in structure.events(f) if e[1] == "structure_break_up"]
    assert ups
    assert ups[0][2] == "choch"


def test_egy_csucs_egyszer_torik() -> None:
    f = frame([*path((100, 110, 10), (110, 104, 10), (104, 115, 10)), 115.0, 114.0, 116.0, 113.0, 117.0])
    breaks = [e for e in structure.events(f) if e[1] == "structure_break_up"]
    assert len(breaks) == len({e[0] for e in breaks})
    assert len(breaks) == 1


# ---------------------------------------------------------------- M6


def test_kitores_utan_visszateszt() -> None:
    # 30 nap bemelegedés (az ATR-nek kell), két csúcs 110-nél (a szint 110,3), kitörés,
    # visszateszt 110,8-ig (a mélypont a szint közelében, a záró fölötte), onnan tovább fel
    f = frame(
        path(
            (96, 100, 30),
            (100, 110, 8),
            (110, 102, 8),
            (102, 110, 8),
            (110, 103, 8),
            (103, 118, 6),
            (118, 110.8, 5),
            (110.8, 125, 10),
        )
        + [125.0] * 5
    )
    got = [name for _, name, _ in breakouts.events(f, walk_levels(f))]
    assert "breakout_up" in got
    assert got[got.index("breakout_up") + 1] == "breakout_up_retest"


def test_hamis_kitores() -> None:
    # gyors visszaesés a szint alá, közben egyetlen nap sem ér a szint közelébe a jó oldalon
    f = frame(
        path(
            (96, 100, 30),
            (100, 110, 8),
            (110, 102, 8),
            (102, 110, 8),
            (110, 103, 8),
            (103, 118, 6),
            (118, 100, 3),
        )
        + [100.0] * 5
    )
    got = [name for _, name, _ in breakouts.events(f, walk_levels(f))]
    assert got[got.index("breakout_up") + 1] == "breakout_up_failed"


# ---------------------------------------------------------------- M1


def impulse_then(retrace_to: float) -> pd.DataFrame:
    # 100 → 130 impulzus, visszaesés `retrace_to`-ig, majd lassú emelkedés (nem éri el a 130-at)
    return frame(
        path((110, 100, 10), (100, 130, 15), (130, retrace_to, 10), (retrace_to, 125, 15)) + [125.0] * 5
    )


@pytest.mark.parametrize(
    ("low", "zone_name"),
    [(122.0, "shallow"), (116.0, "z382"), (113.0, "z500"), (108.0, "golden"), (104.0, "invalid")],
)
def test_a_melyseg_zonaja(low: float, zone_name: str) -> None:
    f = impulse_then(low)
    got = {(name, variant) for _, name, variant, _ in fibonacci.events(f) if name.startswith("fib_up")}
    assert (f"fib_up_{zone_name}", "wick") in got


def test_az_esemeny_a_visszaeses_volgyenek_felismeresekor() -> None:
    f = impulse_then(108.0)
    lows = [p for p in pivots(f) if p.kind == "low" and p.index > 20]
    days = {day for day, name, _, _ in fibonacci.events(f) if name.startswith("fib_up")}
    assert days == {lows[0].index + 5}


def test_nincs_esemeny_ha_az_impulzus_folytatodott() -> None:
    # a visszaesés völgyének felismerése előtt új csúcs: ez nem visszaesés volt
    f = frame(path((110, 100, 10), (100, 130, 15), (130, 118, 6), (118, 140, 4)) + [140.0] * 10)
    assert not [e for e in fibonacci.events(f) if e[1].startswith("fib_up")]


def test_mind_a_negy_valtozat_kulon() -> None:
    f = impulse_then(108.0)
    variants = {variant for _, name, variant, _ in fibonacci.events(f) if name.startswith("fib_up")}
    assert variants == set(fibonacci.VARIANTS)


# ---------------------------------------------------------------- M4


def rising_waves(years: int = 6) -> pd.DataFrame:
    # emelkedő trend, félévenkénti hullámokkal: minden idősíkon magasabb csúcs és völgy
    n = years * 260
    t = np.arange(n)
    c = 100 + t * 0.08 + 12 * np.sin(2 * np.pi * t / 130)
    days = pd.bdate_range("2012-01-02", periods=n).date
    return pd.DataFrame({"date": days, "open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1e6})


def test_emelkedo_trendben_van_egyezes() -> None:
    got = topdown.events(rising_waves())
    ups = [e for e in got if e[1] == "topdown_up"]
    assert ups
    assert all(e[3] == "long" for e in ups)
    assert {e[2] for e in ups} <= {"", "ext_low", "ext_high"}


def test_a_felkesz_heti_gyertya_nem_szamit() -> None:
    # egy hét közepén elvágva ugyanaz, mintha a hetet ki sem vágtuk volna (lásd a jövőbe-nézés tesztet is)
    f = rising_waves()
    full = topdown.events(f)
    for cut in (703, 704, 705):
        part = topdown.events(f.iloc[:cut].reset_index(drop=True))
        assert part == [e for e in full if e[0] < cut]


# ---------------------------------------------------------------- M9


def test_emelkedo_trendvonal_torese() -> None:
    # emelkedő völgyek 100, 105, 110 egy egyenesen, érintés, majd zuhanás a vonal alá
    f = frame(
        path(
            (104, 100, 6),
            (100, 108, 8),
            (108, 105, 7),
            (105, 113, 8),
            (113, 110, 7),
            (110, 118, 8),
            (118, 95, 12),
        )
        + [95.0] * 5
    )
    got = trendlines.events(f)
    breaks = [e for e in got if e[1] == "trendline_up_break"]
    assert breaks
    assert breaks[0][3] == "short"
    assert breaks[0][2] in {"touches_2", "touches_3", "touches_4+"}


# ---------------------------------------------------------------- közös


def test_az_ismetlodes_zar_5_napon_belul_egyszer_enged() -> None:
    events = [(10, "a"), (12, "a"), (15, "a"), (16, "b"), (21, "a")]
    assert lock(events) == [(10, "a"), (15, "a"), (16, "b"), (21, "a")]


def test_a_futas_az_uj_szabalyokat_is_mei() -> None:
    rules = {str(r["rule"]) for r in instrument_events("CZ00001", random_walk(3))}
    for prefix in ("structure_break_", "fib_", "topdown_", "trendline_", "breakout_"):
        assert any(r.startswith(prefix) for r in rules), prefix
