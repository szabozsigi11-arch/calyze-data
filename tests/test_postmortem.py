"""A post-mortem csak a mért tényeket írja le, és csak a rossz napokról."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from pipeline.publish.postmortem import BAD_DAY_GAP, MIN_RESOLVED, build_postmortems


def day(n: int, model_hits: int, baseline_hits: int, sectors: list[str] | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    hit = np.array([1.0] * model_hits + [0.0] * (n - model_hits))
    base = np.array([1.0] * baseline_hits + [0.0] * (n - baseline_hits))
    return pd.DataFrame(
        {
            "instrument_id": [f"CZ{i:05d}" for i in range(n)],
            "session": date(2026, 9, 18),
            "target_session": date(2026, 9, 25),
            "horizon": 5,
            "regime": "normal",
            "actual_return": rng.normal(-0.01, 0.02, n),
            "prob_up": np.where(hit == 0, 0.6, 0.55),
            "hit": hit,
            "baseline_hit": base,
            "sector": sectors if sectors is not None else ["Industrials"] * n,
        }
    )


def universe_of(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[["instrument_id", "sector"]].drop_duplicates()


def test_a_rossz_nap_jelentest_kap() -> None:
    d = day(100, model_hits=40, baseline_hits=55)
    reports = build_postmortems(d.drop(columns=["sector"]), universe_of(d))
    assert len(reports) == 1
    r = reports[0]
    assert (r["n"], r["hits"], r["baseline_hits"], r["misses"]) == (100, 40, 55, 60)
    # A hírt nem figyeljük még — a csomag ezt kimondja, nem hallgatja el.
    assert r["news_tracked"] is False


def test_a_kuszob_alatti_nap_nem_rossz() -> None:
    """4 pont lemaradás még nem „rossz nap” — a küszöb 5, és előre rögzült."""
    assert BAD_DAY_GAP == 0.05
    d = day(100, model_hits=51, baseline_hits=55)
    assert build_postmortems(d.drop(columns=["sector"]), universe_of(d)) == []


def test_a_jo_naprol_nem_keszul_jelentes() -> None:
    d = day(100, model_hits=70, baseline_hits=50)
    assert build_postmortems(d.drop(columns=["sector"]), universe_of(d)) == []


def test_keves_becslesbol_nincs_jelentes() -> None:
    d = day(MIN_RESOLVED - 1, model_hits=5, baseline_hits=20)
    assert build_postmortems(d.drop(columns=["sector"]), universe_of(d)) == []


def test_a_kiemelkedo_szektort_megnevezi() -> None:
    # 100 becslés, 20 félvezető; a 60 hibából 18 félvezető (30% a 20%-kal szemben).
    sectors = ["Semiconductors"] * 20 + ["Other"] * 80
    d = day(100, model_hits=40, baseline_hits=55, sectors=sectors)
    # A hibák a lista végén vannak (hit=0): rendezzük át, hogy 18 félvezető hibázzon.
    d["hit"] = [0.0] * 18 + [1.0] * 2 + [0.0] * 42 + [1.0] * 38
    reports = build_postmortems(d.drop(columns=["sector"]), universe_of(d))
    sector = reports[0]["sector"]
    assert sector is not None
    assert sector["sector"] == "Semiconductors"
    assert sector["misses"] == 18


def test_a_pontosan_10_pontos_tobblet_is_szamit() -> None:
    """„Legalább 10 pont” — a határ benne van, a lebegőpontos kerekítés ellenére is.

    Ez a teszt egy valódi hibát fogott meg: 18/60 − 20/100 a gépen
    0,0999999…, és a szektor kimaradt volna.
    """
    sectors = ["Semiconductors"] * 20 + ["Other"] * 80
    d = day(100, model_hits=40, baseline_hits=55, sectors=sectors)
    d["hit"] = [0.0] * 18 + [1.0] * 2 + [0.0] * 42 + [1.0] * 38
    sector = build_postmortems(d.drop(columns=["sector"]), universe_of(d))[0]["sector"]
    assert sector is not None
    assert sector["excess"] == 0.1


def test_ha_egyik_szektor_sem_emelkedik_ki_nem_nevez_meg_egyet() -> None:
    """Nem keresünk mintázatot ott, ahol nincs."""
    d = day(100, model_hits=40, baseline_hits=55, sectors=["A", "B", "C", "D"] * 25)
    d["hit"] = np.tile([0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0], 10)
    reports = build_postmortems(d.drop(columns=["sector"]), universe_of(d))
    assert reports[0]["sector"] is None
