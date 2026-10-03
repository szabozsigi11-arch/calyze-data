"""Az állapotoldal nem szépíthet: ha nincs futás, ki kell mondania."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from pipeline.status.build import STALE_AFTER_DAYS, Manifest, freshness, partial, render


def manifest(session: str, forecasts: int = 1848, instruments: int = 616) -> Manifest:
    return Manifest(
        session=date.fromisoformat(session),
        made_at=f"{session}T06:00:00+00:00",
        instruments=instruments,
        universe=620,
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


def test_a_reszleges_napot_megjeloli() -> None:
    """A forrás néha az univerzum töredékére ad árat. Nem töröljük, de kiírjuk."""
    thin = manifest("2026-09-22", forecasts=3, instruments=1)
    assert partial(thin) is True
    assert partial(manifest("2026-09-23")) is False

    page = render([thin, manifest("2026-09-23")], date(2026, 9, 24))
    assert "partial" in page
    # A jelölés szövegként is ott van, nem csak színnel (spec/04, A7).
    assert ">partial</span>" in page


def test_mind_a_negy_eszkozosztaly_es_a_kiesett_nap_latszik() -> None:
    """A kiesett nap kiesettként, az elkésett lenyomat késettként látszik (docs/elo-futas.md)."""
    from datetime import UTC, datetime

    from pipeline.status.build import ASSETS, Section, late, missed_days

    equity = ASSETS[0]
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    have = [manifest(d) for d in ("2026-09-28", "2026-10-01")]
    missed = missed_days(equity, have, now)
    # 10-02 (péntek) határideje hétfő nyitás: még nem kiesett.
    assert date(2026, 9, 29) in missed
    assert date(2026, 9, 30) in missed
    assert date(2026, 10, 2) not in missed
    # A 09-24-i becslés 09-26-án készült: a 09-25-i nyitás után.
    slow = Manifest(
        session=date(2026, 9, 24),
        made_at="2026-09-26T00:45:52+00:00",
        instruments=616,
        universe=620,
        forecasts=1848,
        sha256="a" * 64,
        model="lgbm-core v1",
        status="saved",
    )
    assert late(slow, equity.deadline)
    assert not late(manifest("2026-09-28"), equity.deadline)

    sections = [Section(equity, equity.title, equity.note, [*have, slow], missed)]
    sections += [Section(a, a.title, a.note, [], missed_days(a, [], now)) for a in ASSETS[1:]]
    page = render(have, now.date(), sections)
    for title in ("Stocks and ETFs", "Crypto", "Currencies", "Treasury yields"):
        assert title in page
    assert ">missed</span>" in page
    assert ">late</span>" in page
    # A kripto élő kezdete (10-02) határideje 10-03 06:00 UTC volt: kiesett.
    assert missed_days(ASSETS[1], [], now) == [date(2026, 10, 2)]
    # A deviza és a kötvény még nem indult el: nincs kiesett nap.
    assert missed_days(ASSETS[2], [], now) == []
    assert missed_days(ASSETS[3], [], now) == []
