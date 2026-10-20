"""Kalibrációs edzés: vak kérdések, a baseline csak a múltat látja."""

from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

from pipeline.practice.build import WINDOW, baseline_prob, build, question


def walk(n: int = 2500, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    days = [date(2008, 1, 1) + timedelta(days=i) for i in range(n)]
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n))), index=days)


def panels() -> dict[str, dict[str, pd.Series]]:
    return {
        "equity": {f"E{i}": walk(seed=i) for i in range(4)},
        "crypto": {"C0": walk(seed=10)},
        "fx": {"F0": walk(seed=20)},
    }


def test_a_kerdes_vak_nev_es_datum_nelkul() -> None:
    qs = build(panels(), n=60)
    assert len(qs) == 60
    text = json.dumps(qs)
    for leak in ("E0", "C0", "F0", "2010", "2011", "date", "ticker", "instrument"):
        assert leak not in text
    q = qs[0]
    assert len(q["closes"]) == WINDOW
    assert q["closes"][-1] == 100.0
    assert len(q["after"]) == q["horizon"]


def test_az_aranyok_es_az_ismetelhetoseg() -> None:
    qs = build(panels(), n=60)
    counts = pd.Series([q["asset"] for q in qs]).value_counts().to_dict()
    assert counts == {"equity": 30, "crypto": 15, "fx": 15}
    # Rögzített mag: ugyanaz a bemenet ugyanazt a bankot adja.
    assert [q["id"] for q in qs] == [q["id"] for q in build(panels(), n=60)]


def test_a_baseline_nem_lat_a_jovobe() -> None:
    s = walk().to_numpy()
    before = baseline_prob(s, 1000, 20)
    changed = s.copy()
    changed[1001:] = changed[1001:] * 3  # a kérdés napja utáni adat megváltozik
    assert baseline_prob(changed, 1000, 20) == before


def test_a_kimenetel_a_folytatasbol_jon() -> None:
    s = np.linspace(50, 200, 800)  # mindig emelkedik
    q = question(s, 600, 20, "equity")
    assert q is not None
    assert q["up"] is True
    assert q["after"][-1] > 100
    assert q["baseline_prob"] == 0.99  # mindig emelkedett, a felső korlát
