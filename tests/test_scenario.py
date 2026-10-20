"""Forgatókönyv (`docs/forgatokonyv.md`): hírmentes ablak, feltételes eloszlás, mérés."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from pipeline.scenario.calibrate import calibration, calm_windows, instrument_shares, measure, prob_up

DAYS = [date(2020, 1, 1) + timedelta(days=i) for i in range(10)]


def test_az_ablak_a_becsles_utani_napokat_nezi() -> None:
    flags = pd.DataFrame({"instrument_id": "A", "date": DAYS, "flag": [False] * 10})
    flags.loc[4, "flag"] = True  # az 5. napon szólt a detektor
    scored = pd.DataFrame({"instrument_id": "A", "date": DAYS, "horizon": 2})
    calm = calm_windows(scored, flags, pd.Series(dtype=bool))
    # A 2. és a 3. nap ablakába esik a jelzés (a 4. nap a becslés napja: azt már látta).
    assert list(calm[:5]) == [1.0, 1.0, 0.0, 0.0, 1.0]
    # Az utolsó két napnak még nincs lezárt ablaka.
    assert calm[8:].isna().all()


def test_a_piaci_jel_is_hirnek_szamit() -> None:
    flags = pd.DataFrame({"instrument_id": "A", "date": DAYS, "flag": [False] * 10})
    market = pd.Series({DAYS[6]: True})
    scored = pd.DataFrame({"instrument_id": "A", "date": DAYS, "horizon": 1})
    calm = calm_windows(scored, flags, market)
    assert calm[5] == 0.0
    assert calm[6] == 1.0


def synthetic(n_days: int = 900, instruments: int = 6, seed: int = 3) -> pd.DataFrame:
    """Becslések, ahol a hírmentes ablakok hibája feleakkora, mint a többié."""
    rng = np.random.default_rng(seed)
    rows = []
    start = date(2015, 1, 1)
    for i in range(instruments):
        for d in range(n_days):
            calm = rng.random() < 0.6
            point = rng.normal(0.002, 0.01)
            scale = 0.03
            y = point + rng.normal(0, scale * (0.5 if calm else 1.5))
            rows.append(
                {
                    "instrument_id": f"I{i}",
                    "date": start + timedelta(days=d),
                    "horizon": 5,
                    "expected_return": point,
                    "scale": scale,
                    "y": y,
                    "regime": "calm" if d % 3 else "stressed",
                    "fold": d // 150,
                    "prob_up__naive": 0.52,
                    "calm": 1.0 if calm else 0.0,
                }
            )
    return pd.DataFrame(rows)


def test_a_hirmentes_sav_szukebb_es_a_kvantilisek_rendezettek() -> None:
    cal = calibration(synthetic())
    entry = cal["horizons"]["5"]["all"]
    assert entry["band_q"] < entry["band_q_all"]
    q = entry["quantiles"]
    assert len(q) == 199
    assert q == sorted(q)
    assert 0.5 < entry["calm_share"] < 0.7


def test_30_hirmentes_ablak_alatt_nincs_eloszlas() -> None:
    small = synthetic(n_days=8, instruments=2)
    entry = calibration(small)["horizons"]["5"]["all"]
    assert "quantiles" not in entry
    assert entry["calm_windows"] < 30


def test_a_meres_csak_korabbi_foldokbol_kalibral_es_verdiktet_ad() -> None:
    records = measure(synthetic())
    direction = [r for r in records if r["metric"] == "direction_accuracy"]
    assert direction
    assert {r["regime"] for r in direction} >= {"all", "calm", "stressed"}
    for r in direction:
        assert r["baseline"] == "naive"
        assert r["baseline_value"] is not None
        assert r["n_tests"] == len(direction)  # saját FDR-család
    coverage = next(r for r in records if r["metric"] == "coverage" and r["regime"] == "all")
    assert abs(coverage["value"] - 0.9) < 0.03


def test_az_eselyt_ugyanabbol_az_eloszlasbol_szamolja() -> None:
    errors = np.array([-1.0, 0.0, 1.0, 2.0])
    # pont = 0: P(y > 0) = P(hiba > 0) = 2/4
    assert prob_up(errors, np.array([0.0]), np.array([1.0]))[0] == 0.5


def test_papironkenti_hanyad_30_alatt_ures() -> None:
    shares = instrument_shares(synthetic(n_days=20, instruments=2))
    assert shares["I0"] == [None]
