"""Az értesítések piaci összefoglalója (pipeline/notify.py)."""

from datetime import date

from pipeline.notify import calendar_rows, digest, session_rows


def latest(session: str, **extra: object) -> dict[str, object]:
    return {
        "session": session,
        "resolved": {"on": "2026-09-25", "count": 616, "hits": 247, "baseline_hits": 247},
        "market_shock": {"status": "ok", "signals": [], "withheld": False, "instruments_flagged": 3},
        "upcoming_events": [
            {"id": "nfp-2026-10-02", "kind": "nfp", "day": "2026-10-02", "time_et": "08:30"},
            {"id": "cpi-2026-10-14", "kind": "cpi", "day": "2026-10-14", "time_et": "08:30"},
        ],
        **extra,
    }


def test_csak_piaci_szamok_mennek():
    d = digest(latest("2026-10-01"))
    assert set(d) == {"session", "resolved", "shock", "events_next_session", "week_end"}
    assert d["resolved"]["count"] == 616


def test_a_kovetkezo_kereskedesi_nap_esemenye_holnapi():
    assert digest(latest("2026-10-01"))["events_next_session"] == [
        {"kind": "nfp", "day": "2026-10-02", "time_et": "08:30"}
    ]
    assert digest(latest("2026-09-30"))["events_next_session"] == []


def test_a_het_utolso_napja_utan_heti_attekinto():
    assert digest(latest("2026-10-02"))["week_end"] is True  # péntek
    assert digest(latest("2026-10-01"))["week_end"] is False


def test_a_naptar_a_zaras_idopontjaval_megy():
    rows = session_rows(date(2026, 10, 2))
    by_day = {r["session"]: r["close_at"] for r in rows}
    assert "2026-10-03" not in by_day  # szombat
    assert by_day["2026-10-02"].startswith("2026-10-02T20:00")  # 16:00 New York, nyári idő
    assert by_day["2026-11-27"].startswith("2026-11-27T18:00")  # hálaadás utáni rövidített nap, 13:00
    assert "2026-11-26" not in by_day  # hálaadás
    assert len(rows) < 400  # az adatbázis ennél többet nem fogad el


def test_a_kripto_papirok_24_7_es_naptarat_kapnak():
    rows = calendar_rows()
    assert len(rows) == 50
    assert rows[0] == {"instrument_id": "CZ00621", "calendar": "24/7"}
    assert {r["calendar"] for r in rows} == {"24/7"}
