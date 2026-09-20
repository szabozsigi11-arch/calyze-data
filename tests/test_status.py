"""Az állapotoldal nem szépíthet: ha nincs futás, ki kell mondania."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from pipeline.status.build import STALE_AFTER_DAYS, Manifest, freshness, render


def manifest(session: str, forecasts: int = 1848) -> Manifest:
    return Manifest(
        session=date.fromisoformat(session),
        made_at=f"{session}T06:00:00+00:00",
        instruments=616,
        forecasts=forecasts,
        sha256="52882a2529782b0e6254d4ccefdb6e2df6d1aa9b5749864f5e3507bd52e24fda",
        model="lgbm-core v1",
        status="saved",
    )


def test_nincs_futas_eseten_kimondja() -> None:
    state, sentence = freshness(None, date(2026, 9, 20))
    assert state == "no-runs"
    assert "No forecast package" in sentence


def test_friss_futas() -> None:
    state, _ = freshness(manifest("2026-09-18"), date(2026, 9, 20))
    assert state == "current"


def test_elavult_futas_eseten_a_kesest_is_kiirja() -> None:
    today = date(2026, 9, 30)
    latest = manifest("2026-09-18")
    state, sentence = freshness(latest, today)
    assert state == "stale"
    assert "12 days ago" in sentence
    assert (today - latest.session).days > STALE_AFTER_DAYS


def test_az_oldal_nem_kozol_arat_sem_becslest() -> None:
    """A licenc miatt a lenyomat és a darabszám mehet ki, más semmi."""
    html = render([manifest("2026-09-18")], date(2026, 9, 20))
    assert "52882a2529782b0e" in html
    assert "1848" in html

    # Egyetlen papír neve sem jelenhet meg: ha valaha instrumentumonkénti
    # sor kerülne az oldalra, ez a teszt bukik.
    universe = (Path(__file__).resolve().parents[1] / "pipeline/universe/instruments.csv").read_text(
        encoding="utf-8"
    )
    tickers = [line.split(",")[1] for line in universe.splitlines()[1:201] if "," in line]
    words = set(re.findall(r"[A-Z]{2,5}", html))
    assert not (words & set(tickers))


def test_a_jogi_kozles_ott_van() -> None:
    html = render([], date(2026, 9, 20))
    assert "not investment advice" in html
