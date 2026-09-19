"""Look-ahead tesztek (spec/06, 3. fejezet; spec/12, 8. fejezet).

Az elv: ha a t nap UTÁNI adatot tetszőlegesen megváltoztatjuk, a t napig
számolt feature-öknek és rezsim-címkéknek bitre azonosnak kell maradniuk.
Ha valamelyik feature a jövőbe lát, ez a teszt elbukik.
"""

from datetime import date

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from pipeline.calendar import sessions
from pipeline.features.regime import CROSS_MARKET, compute_regime, expanding_percentile
from pipeline.features.technical import add_cross_sectional, compute_technical

DAYS = sessions(date(2024, 1, 2), date(2026, 9, 18))


def synthetic(ids: list[str], seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in ids:
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, len(DAYS))))
        factor = np.linspace(0.9, 1.0, len(DAYS))  # osztalék miatti igazítás
        rows.append(
            pd.DataFrame(
                {
                    "instrument_id": i,
                    "date": DAYS,
                    "open": close * (1 + rng.normal(0, 0.003, len(DAYS))),
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "adj_close": close * factor,
                    "tr_close": close * factor,
                    "volume": rng.integers(1_000_000, 5_000_000, len(DAYS)).astype(float),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def perturb_after(prices: pd.DataFrame, cut: date, seed: int) -> pd.DataFrame:
    """A cut utáni összes árat és volument véletlenszerűen átírja."""
    rng = np.random.default_rng(seed)
    out = prices.copy()
    future = out["date"] > cut
    scale = rng.uniform(0.5, 2.0, future.sum())
    for col in ("open", "high", "low", "close", "adj_close", "tr_close"):
        out.loc[future, col] = out.loc[future, col] * scale
    out.loc[future, "volume"] = out.loc[future, "volume"] * rng.uniform(0.1, 10, future.sum())
    return out


UNIVERSE = pd.DataFrame(
    {
        "instrument_id": ["A", "B", "C"] + [f"E{i}" for i in range(len(CROSS_MARKET))],
        "ticker": ["AAA", "BBB", "CCC", *CROSS_MARKET],
        "asset_class": ["equity"] * 3 + ["etf"] * len(CROSS_MARKET),
        "sector": ["Tech", "Tech", "Energy"] + ["x"] * len(CROSS_MARKET),
    }
)


@settings(max_examples=15, deadline=None)
@given(cut_index=st.integers(min_value=260, max_value=len(DAYS) - 2), seed=st.integers(0, 10_000))
def test_features_never_see_the_future(cut_index, seed):
    cut = DAYS[cut_index]
    prices = synthetic(["A", "B", "C"], seed)
    base = add_cross_sectional(compute_technical(prices), UNIVERSE)
    moved = add_cross_sectional(compute_technical(perturb_after(prices, cut, seed + 1)), UNIVERSE)
    past = base["date"] <= cut
    pd.testing.assert_frame_equal(
        base[past].reset_index(drop=True), moved[moved["date"] <= cut].reset_index(drop=True)
    )


@settings(max_examples=10, deadline=None)
@given(cut_index=st.integers(min_value=300, max_value=len(DAYS) - 2), seed=st.integers(0, 10_000))
def test_regime_never_sees_the_future(cut_index, seed):
    cut = DAYS[cut_index]
    prices = synthetic([f"E{i}" for i in range(len(CROSS_MARKET))], seed)
    base = compute_regime(prices, UNIVERSE)
    moved = compute_regime(perturb_after(prices, cut, seed + 1), UNIVERSE)
    pd.testing.assert_frame_equal(
        base[base["date"] <= cut].reset_index(drop=True), moved[moved["date"] <= cut].reset_index(drop=True)
    )


def test_features_change_after_the_cut():
    # Kontroll: a perturbáció tényleg hat — különben a fenti teszt semmit nem bizonyítana.
    prices = synthetic(["A"], 1)
    cut = DAYS[400]
    a = compute_technical(prices)
    b = compute_technical(perturb_after(prices, cut, 2))
    assert not a[a["date"] > cut]["ret_20"].equals(b[b["date"] > cut]["ret_20"])


def test_expanding_percentile_uses_only_the_past():
    x = pd.Series([1.0] * 300 + [100.0])
    pct = expanding_percentile(x)
    assert pct.iloc[-1] == 1.0  # a mostani érték a valaha látott legnagyobb
    assert pct.iloc[:251].isna().all()  # 252 session előtt nincs címke


def test_regime_labels_have_three_states_on_mixed_volatility():
    prices = synthetic([f"E{i}" for i in range(len(CROSS_MARKET))], 3)
    # Egy nyugodt és egy viharos szakasz: a címkék közt mindhárom állapotnak meg kell jelennie.
    calm = prices["date"] < date(2025, 6, 1)
    for col in ("open", "high", "low", "close", "adj_close", "tr_close"):
        base = prices.groupby("instrument_id")[col].transform("first")
        noise = np.exp(np.random.default_rng(4).normal(0, 0.06, (~calm).sum()).cumsum() / 20)
        prices.loc[~calm, col] = base[~calm] * noise
    labels = set(compute_regime(prices, UNIVERSE)["regime"].dropna())
    assert {"calm", "normal", "stressed"} <= labels
