"""Purged walk-forward felosztás embargóval (spec/06, 3. fejezet).

Soha nem véletlen felosztás és soha nem k-fold: az időrend szigorú.

    tanító ablak ─┤ purge (h nap) ├─ teszt ablak ─┤ embargo (h nap) ├─ …

- **Purge:** a teszt kezdete előtti h nap kiesik a tanításból, mert azoknak a
  soroknak a címkéje már a teszt időszakába nyúlik (átfedő horizont).
- **Embargo:** a teszt után is kihagyunk h napot a következő tanításból, hogy
  a teszt időszak hatása ne szivárogjon vissza.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Fold:
    train_end: date
    test_start: date
    test_end: date


def walk_forward(
    sessions: list[date], horizon: int, test_sessions: int = 252, min_train: int = 756
) -> list[Fold]:
    """Egymás utáni teszt-ablakok, bővülő tanító ablakkal.

    Args:
        sessions: a kereskedési napok időrendben.
        horizon: a címke hossza sessionben (ennyi a purge és az embargo is).
        test_sessions: egy teszt-ablak hossza (alapból kb. egy év).
        min_train: az első fold előtt ennyi session kell tanításra.
    """
    folds: list[Fold] = []
    start = min_train
    while start + test_sessions <= len(sessions):
        test = sessions[start : start + test_sessions]
        # A tanítás vége: a teszt kezdete előtt h nappal (purge).
        train_end = sessions[max(0, start - horizon - 1)]
        folds.append(Fold(train_end=train_end, test_start=test[0], test_end=test[-1]))
        start += test_sessions
    return folds


def train_mask(dates, fold: Fold, horizon: int, sessions: list[date]) -> list[bool]:
    """Egy fold tanító sorai: minden, aminek a CÍMKÉJE is a purge előtt véget ér."""
    index = {d: i for i, d in enumerate(sessions)}
    end_i = index[fold.train_end]
    return [(d in index) and (index[d] + horizon <= end_i) for d in dates]
