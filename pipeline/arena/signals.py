"""A jelzés-szabályok kiszámítása (spec/11, Fázis 2; `docs/jelzes-definiciok.md`).

A definíciók a mérés ELŐTT rögzültek abban a dokumentumban, és itt csak
végrehajtjuk őket. Ha egy szabály itt eltérne a leírtaktól, az hiba —
nem a dokumentumot igazítjuk a kódhoz, hanem fordítva.

Egy jelzés egyetlen sor: melyik papír, melyik napon, melyik szabály, milyen
irányban. A kimenetelt nem itt számoljuk; azt a kiértékelés teszi, ugyanazzal
a protokollal, amivel a modellt méri.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# A szabály nevéhez tartozó irány. Ez a lista a szerződés: ami itt nincs, azt
# nem mérjük, és ami itt van, annak a definíciós dokumentumban is szerepelnie
# kell ugyanezzel a néven.
DIRECTIONS: dict[str, str] = {
    "macd_cross_up": "long",
    "macd_cross_down": "short",
    "golden_cross": "long",
    "death_cross": "short",
    "close_above_ema200": "long",
    "close_below_ema200": "short",
    "rsi_oversold": "long",
    "rsi_overbought": "short",
    "bollinger_lower": "long",
    "bollinger_upper": "short",
    "momentum_top_decile": "long",
    "volume_spike_up": "long",
}

RULES: list[str] = list(DIRECTIONS)

# Minimális előzmény a jelzés napján (közös szabály 6.).
MIN_HISTORY_SESSIONS = 252

# A forgalmi kiugrás küszöbe a 20 napos mediánhoz képest.
VOLUME_SPIKE = 3.0


def _first_of_each_run(condition: pd.Series) -> pd.Series:
    """Az ismétlődés-zár (közös szabály 5.).

    Egy igaz szakaszból csak az ELSŐ nap marad igaz. A zár akkor oldódik fel,
    amikor a feltétel megszűnik — pontosan ezt jelenti az, hogy a következő
    igaz szakasz újra számít.
    """
    flag = condition.fillna(False).astype(bool)
    return flag & ~flag.shift(1, fill_value=False)


def instrument_signals(frame: pd.DataFrame) -> pd.DataFrame:
    """Egy papír jelzései, dátum szerint rendezett OHLCV-ből.

    A bemenet oszlopai: `date`, `open`, `high`, `low`, `close`, `volume`.
    A kimenet oszlopai: `date`, `rule`.
    """
    data = frame.sort_values("date").reset_index(drop=True)
    close = data["close"].astype("float64")

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()

    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    ema200 = close.ewm(span=200, adjust=False, min_periods=200).mean()

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    band_low = sma20 - 2 * std20
    band_high = sma20 + 2 * std20

    rsi = _rsi(close)

    volume = data["volume"].astype("float64")
    volume_median = volume.rolling(20).median()

    above = {
        "macd": macd > macd_signal,
        "sma": sma50 > sma200,
        "ema200": close > ema200,
    }

    conditions = {
        "macd_cross_up": above["macd"] & ~above["macd"].shift(1, fill_value=False),
        "macd_cross_down": ~above["macd"] & above["macd"].shift(1, fill_value=False) & macd.notna(),
        "golden_cross": above["sma"] & ~above["sma"].shift(1, fill_value=False),
        "death_cross": ~above["sma"] & above["sma"].shift(1, fill_value=False) & sma200.notna(),
        "close_above_ema200": above["ema200"] & ~above["ema200"].shift(1, fill_value=False),
        "close_below_ema200": ~above["ema200"] & above["ema200"].shift(1, fill_value=False) & ema200.notna(),
        "rsi_oversold": (rsi < 30) & (rsi.shift(1) >= 30),
        "rsi_overbought": (rsi > 70) & (rsi.shift(1) <= 70),
        "bollinger_lower": close < band_low,
        "bollinger_upper": close > band_high,
        "volume_spike_up": (volume >= VOLUME_SPIKE * volume_median) & (close > close.shift(1)),
    }

    # A keresztezéses szabályok maguk csak az átlépés napján igazak, tehát az
    # ismétlődés-zár rájuk nem változtat semmit. A sávos szabályoknál viszont
    # döntő: egy hosszabb szalagon kívüli szakasz egyetlen jelzés.
    fired = {name: _first_of_each_run(series) for name, series in conditions.items()}

    history = np.arange(1, len(data) + 1)
    enough = pd.Series(history >= MIN_HISTORY_SESSIONS, index=data.index)

    rows = []
    for name, series in fired.items():
        days = data.loc[series & enough, "date"]
        if len(days) > 0:
            rows.append(pd.DataFrame({"date": days.to_numpy(), "rule": name}))
    if not rows:
        return pd.DataFrame(columns=["date", "rule"])
    return pd.concat(rows, ignore_index=True).sort_values(["date", "rule"]).reset_index(drop=True)


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder-féle RSI (0–100). Ugyanaz a képlet, mint a feature-tábláé."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def cross_sectional_signals(prices: pd.DataFrame) -> pd.DataFrame:
    """A `momentum_top_decile` szabály: ehhez az egész univerzum kell.

    A 12-1 hónapos momentum az utolsó hónapot kihagyja (a rövid távú
    visszafordulás miatt). A felső tizedet naponta, a **mezőnyhöz képest**
    számoljuk — a küszöb tehát nem egy fix szám, hanem az aznapi rangsor.

    Az ismétlődés-zár itt is él: egy papír mindaddig egyetlen jelzés, amíg ki
    nem esik a felső tizedből.
    """
    if prices.empty:
        return pd.DataFrame(columns=["instrument_id", "date", "rule"])

    frame = prices.sort_values(["instrument_id", "date"]).reset_index(drop=True)
    by_instrument = frame.groupby("instrument_id", sort=False)
    frame["momentum"] = by_instrument["close"].transform(
        lambda c: np.log(c.astype("float64")).shift(21) - np.log(c.astype("float64")).shift(252)
    )
    frame["history"] = by_instrument.cumcount() + 1

    # A rangsor csak akkor értelmes, ha aznap elég papír van a mezőnyben.
    ranked = frame.dropna(subset=["momentum"])
    if ranked.empty:
        return pd.DataFrame(columns=["instrument_id", "date", "rule"])
    cutoff = ranked.groupby("date")["momentum"].transform(lambda s: s.quantile(0.9))
    frame["in_top"] = False
    frame.loc[ranked.index, "in_top"] = ranked["momentum"] >= cutoff

    rows = []
    for instrument, group in frame.groupby("instrument_id", sort=False):
        fired = _first_of_each_run(group["in_top"]) & (group["history"] >= MIN_HISTORY_SESSIONS)
        days = group.loc[fired, "date"]
        if len(days) > 0:
            rows.append(
                pd.DataFrame(
                    {"instrument_id": instrument, "date": days.to_numpy(), "rule": "momentum_top_decile"}
                )
            )
    if not rows:
        return pd.DataFrame(columns=["instrument_id", "date", "rule"])
    return pd.concat(rows, ignore_index=True)


def all_signals(prices: pd.DataFrame) -> pd.DataFrame:
    """Minden szabály jelzései az egész univerzumra.

    Kimenet: `instrument_id`, `date`, `rule`, `direction`.
    """
    if prices.empty:
        return pd.DataFrame(columns=["instrument_id", "date", "rule", "direction"])

    parts = []
    for instrument, group in prices.groupby("instrument_id", sort=False):
        signals = instrument_signals(group)
        if not signals.empty:
            parts.append(signals.assign(instrument_id=instrument))
    parts.append(cross_sectional_signals(prices))

    frame = pd.concat([p for p in parts if not p.empty], ignore_index=True)
    frame["direction"] = frame["rule"].map(DIRECTIONS)
    return (
        frame[["instrument_id", "date", "rule", "direction"]]
        .sort_values(["date", "instrument_id", "rule"])
        .reset_index(drop=True)
    )
