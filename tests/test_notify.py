"""Az értesítések piaci összefoglalója (pipeline/notify.py)."""

from pipeline.notify import digest


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
