"""A jelzés-szabályok azt csinálják, amit a definíciós dokumentum mond.

Minden teszt egy állítást ellenőriz a `docs/jelzes-definiciok.md`-ből. Ha egy
teszt elbukik, vagy a kód tér el a definíciótól, vagy a definíció változott —
és mindkettő komoly.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from pipeline.arena.signals import (
    DIRECTIONS,
    MIN_HISTORY_SESSIONS,
    RULES,
    _first_of_each_run,
    all_signals,
    instrument_signals,
)

DOC = "docs/jelzes-definiciok.md"


def series(
    values: list[float], volume: list[float] | None = None, instrument: str = "CZ00001"
) -> pd.DataFrame:
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(len(values))]
    return pd.DataFrame(
        {
            "instrument_id": instrument,
            "date": days,
            "open": values,
            "high": [v * 1.01 for v in values],
            "low": [v * 0.99 for v in values],
            "close": values,
            "volume": volume if volume is not None else [1_000_000.0] * len(values),
        }
    )


def test_minden_szabaly_szerepel_a_dokumentumban() -> None:
    """A kód és a definíciós dokumentum nem térhet el egymástól."""
    text = open(DOC, encoding="utf-8").read()
    for rule in RULES:
        assert f"`{rule}`" in text, f"{rule} nincs a definíciós dokumentumban"


def test_az_ismetlodes_zar_csak_az_elso_napot_hagyja_meg() -> None:
    """Közös szabály 5.: egy igaz szakaszból csak az első nap számít."""
    condition = pd.Series([False, True, True, True, False, True])
    assert list(_first_of_each_run(condition)) == [False, True, False, False, False, True]


def test_a_rovid_elozmenyu_papir_nem_ad_jelzest() -> None:
    """Közös szabály 6.: 252 kereskedési nap előzmény kell."""
    # Erős zuhanás a legelején: RSI-jelzés lenne, de nincs elég előzmény.
    values = [100.0] * 20 + [100.0 - i for i in range(1, 30)]
    assert len(values) < MIN_HISTORY_SESSIONS
    assert instrument_signals(series(values)).empty


def test_az_rsi_tulveteli_jelzes_a_lefele_atlepeskor_szol() -> None:
    """A feltétel nem „RSI < 30”, hanem „30 alá esik, miután fölötte volt”."""
    # Elég hosszú, sima emelkedés (magas RSI), majd tartós esés.
    values = [100.0 + i * 0.3 for i in range(300)] + [190.0 - i * 2.0 for i in range(40)]
    signals = instrument_signals(series(values))
    oversold = signals[signals["rule"] == "rsi_oversold"]
    assert len(oversold) == 1, "a tartós alacsony RSI egyetlen jelzés, nem húsz"


def test_a_bollinger_szakasz_egyetlen_jelzes() -> None:
    """A szalagon kívüli több napos szakasz egyetlen megfigyelés.

    Nem azt állítjuk, hogy az egész idősor egy jelzést ad — külön epizódok
    külön jelzések. Azt állítjuk, hogy EGY epizód egy jelzés.
    """
    rng = np.random.default_rng(7)
    values = list(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))))
    breakout_from = len(values)
    # Tartós kitörés a felső szél fölé: hét egymást követő napon kívül marad.
    values += [values[-1] * (1 + 0.03 * i) for i in range(1, 8)]

    frame = series(values)
    breakout_days = set(frame.loc[breakout_from:, "date"])
    signals = instrument_signals(frame)
    during = signals[(signals["rule"] == "bollinger_upper") & signals["date"].isin(breakout_days)]
    assert len(during) == 1, "a hétnapos kitörés egyetlen jelzés"


def test_a_forgalmi_kiugras_csak_emelkedo_napon_szol() -> None:
    """A szabály két feltétele együtt érvényes: kiugró forgalom ÉS pozitív nap."""
    values = [100.0 + i * 0.1 for i in range(300)]
    volume = [1_000_000.0] * 300
    volume[290] = 10_000_000.0  # kiugrás emelkedő napon
    up = instrument_signals(series(values, volume))
    assert "volume_spike_up" in set(up["rule"])

    falling = [100.0 - i * 0.1 for i in range(300)]
    down = instrument_signals(series(falling, volume))
    assert "volume_spike_up" not in set(down["rule"])


def test_minden_jelzesnek_van_iranya() -> None:
    rng = np.random.default_rng(3)
    values = list(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, 500))))
    frame = all_signals(series(values))
    assert not frame.empty
    assert set(frame["direction"]) <= {"long", "short"}
    assert frame["direction"].notna().all()
    for rule, direction in frame[["rule", "direction"]].drop_duplicates().itertuples(index=False):
        assert DIRECTIONS[rule] == direction


def test_a_kereszt_metszeti_szabaly_a_mezonyhoz_kepest_mer() -> None:
    """A felső tized nem fix küszöb, hanem az aznapi rangsor teteje."""
    rng = np.random.default_rng(11)
    frames = []
    for i in range(1, 13):
        drift = 0.002 if i == 1 else 0.0
        values = list(100 * np.exp(np.cumsum(rng.normal(drift, 0.01, 400))))
        frames.append(series(values, instrument=f"CZ{i:05d}"))
    prices = pd.concat(frames, ignore_index=True)

    frame = all_signals(prices)
    top = frame[frame["rule"] == "momentum_top_decile"]
    assert not top.empty
    # A jóval erősebb papírnak benne kell lennie a felső tizedben.
    assert "CZ00001" in set(top["instrument_id"])
