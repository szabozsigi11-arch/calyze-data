"""Az aréna ugyanazt a mércét kapja, mint a modell."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from pipeline.arena.evaluate import HORIZONS, arena, baseline_direction, evaluate_rule, forward_outcomes


def walk(instrument: str, days: int = 900, drift: float = 0.0002, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.012, days)))
    return pd.DataFrame(
        {
            "instrument_id": instrument,
            "date": [date(2020, 1, 1) + timedelta(days=i) for i in range(days)],
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000.0,
        }
    )


def test_a_nyitott_kimenetelt_nem_ertekeljuk_ki() -> None:
    """Az utolsó napokra még nincs jövő — azokra nincs sor."""
    prices = walk("CZ00001", days=100)
    outcomes = forward_outcomes(prices, 20)
    assert len(outcomes) == 80
    assert outcomes["date"].max() == prices["date"].iloc[-21]


def test_a_baseline_iranya_a_papir_sajat_sodrodasa() -> None:
    rising = walk("UP", days=400, drift=0.003, seed=2)
    falling = walk("DOWN", days=400, drift=-0.003, seed=3)
    outcomes = forward_outcomes(pd.concat([rising, falling], ignore_index=True), 20)
    direction = baseline_direction(outcomes)
    assert direction["UP"] is np.True_ or direction["UP"] is True
    assert not direction["DOWN"]


def test_a_mindig_talalo_jelzes_veri_a_baselinet() -> None:
    """Épített eset: a jelzés pontosan az eső napokat találja el, a baseline nem.

    Emelkedő papírt választunk, tehát a naiv baseline iránya „fel”. A jelzés
    `short`, és pontosan azokon a napokon szól, amikor a kimenetel esés —
    így a jelzés találati aránya 1, a baseline-é 0.
    """
    prices = walk("CZ00001", days=500, drift=0.002, seed=5)
    outcomes = forward_outcomes(prices, 5)
    assert baseline_direction(outcomes)["CZ00001"], "a minta emelkedő legyen"

    down_days = outcomes[outcomes["up"] < 0.5].head(200)
    signals = down_days[["instrument_id", "date"]].assign(rule="proba")

    comparison = evaluate_rule(signals, outcomes, "short", 5)
    assert comparison is not None
    assert comparison.value == 1.0
    assert comparison.baseline_value == 0.0
    assert comparison.delta > 0
    # Az effektív mintaszám nem lehet nagyobb a nyersnél: az ablakok átfedik egymást.
    assert comparison.n_eff <= comparison.n


def test_a_veletlen_jelzes_nem_lesz_szignifikans() -> None:
    """Véletlen napokon szóló jelzés nem verheti a baseline-t."""
    prices = walk("CZ00001", days=800, seed=9)
    outcomes = forward_outcomes(prices, 20)
    rng = np.random.default_rng(4)
    picked = outcomes.sample(150, random_state=rng.integers(0, 10_000))
    signals = picked[["instrument_id", "date"]].assign(rule="veletlen")

    comparison = evaluate_rule(signals, outcomes, "long", 20)
    assert comparison is not None
    assert comparison.p_value > 0.01, "a véletlen nem lehet erősen szignifikáns"


def test_az_arena_minden_szabalyt_minden_horizonton_mer() -> None:
    from pipeline.arena.signals import all_signals

    prices = pd.concat([walk(f"CZ{i:05d}", days=900, seed=i) for i in range(1, 6)], ignore_index=True)
    signals = all_signals(prices)
    table = arena(signals, prices)

    assert not table.empty
    assert set(table["horizon"]) <= set(HORIZONS)
    # Minden sorban ott a baseline és a mintaszám — szám baseline nélkül nem megy ki.
    for column in ("value", "baseline_value", "n", "n_eff", "p_value", "verdict"):
        assert column in table.columns
        assert table[column].notna().all()
