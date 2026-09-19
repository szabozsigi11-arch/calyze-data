"""Baseline-család (spec/06, 2. lépés).

Nincs egyetlen baseline: a verdict mindig a **legkeményebb** ellen szól, hogy
ne lehessen könnyű ellenfelet választani. Mindegyik baseline ugyanazt adja,
mint a modell (irány-valószínűség és várható hozam), így ugyanazokkal a
metrikákkal mérhető.

Minden baseline paramétere **kizárólag a tanító ablakból** származik (a
találati arányok, az átlagos hozam, a sáv kvantilise is) — különben a
baseline látná a jövőt, és a modell ehhez képest tűnne jobbnak.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pipeline.model.config import BAND_COVERAGE
from pipeline.model.predictor import scale_of

BASELINE_IDS = ("naive", "momentum", "sector", "buy_hold")


def _sign_bins(frame: pd.DataFrame, column: str) -> np.ndarray:
    values = frame[column].to_numpy(dtype="float64")
    return np.where(np.isnan(values), 0, np.sign(values)).astype(int)


@dataclass
class Baseline:
    """Egy baseline betanított állapota: csak a tanító ablak statisztikái."""

    baseline_id: str
    horizon: int
    #: előjel-csoportonként: (a szabály találati aránya, átlagos hozam)
    by_bin: dict[int, tuple[float, float]] = field(default_factory=dict)
    base_rate: float = 0.5
    mean_return: float = 0.0
    band_q: float = 1.0

    def _bin_column(self) -> str | None:
        if self.baseline_id == "momentum":
            return "ret_20"
        if self.baseline_id == "sector":
            return "sector_ret_20"
        return None

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        n = len(frame)
        column = self._bin_column()
        if column is None:
            # Naiv és buy & hold: a tanító ablak alap találati aránya és átlagos hozama.
            prob = np.full(n, self.base_rate)
            point = np.full(n, self.mean_return)
        else:
            # A baseline azt mondja, amit a tanító ablak mutat: az adott
            # momentum- vagy szektor-irány mellett milyen gyakran emelkedett
            # a papír. Ha a szabály iránya és a mért esély ellentmond
            # egymásnak, a mért esély a mérvadó — különben a baseline-t
            # gyengítenénk, és a modell ehhez képest tűnne jobbnak.
            # Emelkedő piacon ez a valószínűség mindkét csoportban 50% fölött
            # lehet; ilyenkor a szabály iránypontosságban nem ad többletet a
            # naivhoz képest, Brier-pontszámban viszont igen.
            bins = _sign_bins(frame, column)
            prob = np.array([self.by_bin.get(b, (self.base_rate, self.mean_return))[0] for b in bins])
            point = np.array([self.by_bin.get(b, (self.base_rate, self.mean_return))[1] for b in bins])
        scale = scale_of(frame, self.horizon)
        return pd.DataFrame(
            {
                "instrument_id": frame["instrument_id"].to_numpy(),
                "date": frame["date"].to_numpy(),
                "horizon": self.horizon,
                "expected_return": point,
                "prob_up": np.clip(prob, 0.01, 0.99),
                "band_low": point - self.band_q * scale,
                "band_high": point + self.band_q * scale,
            }
        )


def fit_baselines(train: pd.DataFrame, horizon: int) -> dict[str, Baseline]:
    """Mind a négy baseline a tanító ablakból.

    - **naiv (random walk):** az alap találati arány és az átlagos hozam
      (ez a „50% + historikus drift”).
    - **momentum:** az elmúlt 20 nap iránya szerinti csoportban mért
      emelkedési arány (a „folytatódik-e” kérdés mért válasza).
    - **szektor:** a papír szektorának 20 napos iránya.
    - **buy & hold:** mindig tartás; a hozamalapú metrikákhoz.
    """
    target = f"y_{horizon}"
    y = train[target].to_numpy(dtype="float64")
    base_rate = float((y > 0).mean())
    mean_return = float(y.mean())
    scale = scale_of(train, horizon)
    band_q = float(np.quantile(np.abs((y - mean_return) / scale), BAND_COVERAGE))

    out: dict[str, Baseline] = {}
    for baseline_id in BASELINE_IDS:
        b = Baseline(
            baseline_id=baseline_id,
            horizon=horizon,
            base_rate=base_rate,
            mean_return=mean_return,
            band_q=band_q,
        )
        column = b._bin_column()
        if column is not None and column in train.columns:
            bins = _sign_bins(train, column)
            for value in (-1, 0, 1):
                mask = bins == value
                if mask.sum() >= 100:
                    b.by_bin[value] = (float((y[mask] > 0).mean()), float(y[mask].mean()))
        out[baseline_id] = b
    return out


def add_sector_return(features: pd.DataFrame) -> pd.DataFrame:
    """A szektor 20 napos hozama: a papír hozama mínusz a szektorhoz mért többlete."""
    return features.assign(sector_ret_20=features["ret_20"] - features["sector_rel_20"])
