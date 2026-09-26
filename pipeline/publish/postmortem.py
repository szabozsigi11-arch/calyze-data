"""Rossz nap post-mortem (spec/06, 7. fejezet; `docs/postmortem-es-screener.md`).

A pipeline itt csak TÉNYEKET állít elő, szöveget nem. A mondat a felületen
áll össze fordított sablonokból, és ott fut rajta a szólista-ellenőrzés —
így a pipeline nem tud tiltott kifejezést a képernyőre juttatni.

Minden szám a kiértékelt kimenetelekből jön. Ami nincs mérve (hír, sokk),
arról a csomag kimondja, hogy nincs mérve.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Legalább ennyi lezárt becslés kell egy naphoz (és egy horizonthoz).
MIN_RESOLVED = 30
#: Rossz a nap, ha a modell legalább ennyivel a baseline alatt van.
BAD_DAY_GAP = 0.05
#: Egy szektor akkor „emelkedik ki", ha legalább ennyi hiba esik bele …
SECTOR_MIN_MISSES = 5
#: … és a hibák közti aránya legalább ennyivel nagyobb, mint az összesben.
SECTOR_MIN_EXCESS = 0.10


def _standout_sector(day: pd.DataFrame) -> dict[str, object] | None:
    """Az a szektor, ahol a hibák aránya a legjobban meghaladja az összesét.

    `None`, ha egyik sem lépi át mindkét küszöböt — ott nem keresünk
    mintázatot, ahol nincs.
    """
    misses = day[day["hit"] < 0.5]
    if misses.empty or "sector" not in day:
        return None
    overall = day["sector"].fillna("—").value_counts(normalize=True)
    missed = misses["sector"].fillna("—").value_counts()
    best: dict[str, object] | None = None
    for sector, count in missed.items():
        share = count / len(misses)
        # Hat tizedesre kerekítve: a „legalább 10 pont” a pontosan 10-et is
        # jelenti, a lebegőpontos kivonás viszont 0,0999999…-et adna rá.
        excess = round(share - float(overall.get(sector, 0.0)), 6)
        if (
            count >= SECTOR_MIN_MISSES
            and excess >= SECTOR_MIN_EXCESS
            and (
                best is None or excess > float(best["excess"])  # type: ignore[arg-type]
            )
        ):
            best = {
                "sector": str(sector),
                "misses": int(count),
                "miss_share": round(float(share), 4),
                "overall_share": round(float(overall.get(sector, 0.0)), 4),
                "excess": round(float(excess), 4),
            }
    return best


def build_postmortems(outcomes: pd.DataFrame, universe: pd.DataFrame) -> list[dict[str, object]]:
    """Minden rossz lezárási nap tényei, a legfrissebb elöl."""
    if outcomes.empty:
        return []
    sectors = (
        universe.set_index("instrument_id")["sector"] if "sector" in universe else pd.Series(dtype=object)
    )
    data = outcomes.assign(sector=outcomes["instrument_id"].map(sectors))

    reports: list[dict[str, object]] = []
    for (target, horizon), day in data.groupby(["target_session", "horizon"], sort=True):
        n = len(day)
        if n < MIN_RESOLVED:
            continue
        model = float(day["hit"].mean())
        baseline = float(day["baseline_hit"].mean())
        if model - baseline > -BAD_DAY_GAP:
            continue
        misses = day[day["hit"] < 0.5]
        regimes = misses["regime"].fillna("unknown").value_counts()
        returns = day["actual_return"].to_numpy(dtype="float64")
        reports.append(
            {
                "target_session": str(target),
                "horizon": int(horizon),  # type: ignore[call-overload]
                "made_on": str(day["session"].iloc[0]),
                "n": n,
                "hits": int(day["hit"].sum()),
                "baseline_hits": int(day["baseline_hit"].sum()),
                "misses": len(misses),
                "misses_expected_rise": int((misses["prob_up"] > 0.5).sum()),
                "misses_expected_fall": int((misses["prob_up"] <= 0.5).sum()),
                "sector": _standout_sector(day),
                "regime": str(regimes.index[0]) if not regimes.empty else None,
                "regime_share": round(float(regimes.iloc[0] / len(misses)), 4) if not regimes.empty else None,
                "market_median_return": round(float(np.expm1(np.median(returns))), 6),
                "market_rose": int((returns > 0).sum()),
                # A hírrendszer a 3. fázis. Addig kimondjuk, hogy nem figyeljük.
                "news_tracked": False,
            }
        )
    return sorted(reports, key=lambda r: (str(r["target_session"]), int(r["horizon"])), reverse=True)  # type: ignore[call-overload]
