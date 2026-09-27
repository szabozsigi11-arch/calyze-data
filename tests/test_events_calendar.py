"""Az R1 naptár (docs/naptar.md)."""

from datetime import date

import pandas as pd

from pipeline.events import calendar as ev
from pipeline.publish.run import _calendar


def test_a_naptar_50_75_esemeny_egyedi_azonositoval():
    assert 50 <= len(ev.EVENTS) <= 75
    assert len({e.id for e in ev.EVENTS}) == len(ev.EVENTS)


def test_az_s_napon_kozolt_esemeny_mar_az_arban_van():
    # CPI 2026-10-14 08:30: a 10-14-i zárás utáni becslésnek már nem újdonság
    assert "cpi-2026-10-14" not in ev.calendar_flag(date(2026, 10, 14), date(2026, 10, 21))
    assert "cpi-2026-10-14" in ev.calendar_flag(date(2026, 10, 13), date(2026, 10, 14))


def test_a_celnap_meg_az_ablak_resze():
    assert ev.calendar_flag(date(2026, 10, 27), date(2026, 10, 28)) == "fomc-2026-10-28"


def test_ures_ablak_ures_jeloles():
    assert ev.calendar_flag(date(2026, 10, 15), date(2026, 10, 21)) == ""
    assert ev.calendar_flag(date(2026, 10, 15), None) == ""


def test_a_becsles_csomag_oszlopot_kap():
    frame = pd.DataFrame(
        {
            "instrument_id": ["CZ00001", "CZ00001"],
            "session": [date(2026, 9, 25), date(2026, 9, 25)],
            "target_session": [date(2026, 10, 2), None],
        }
    )
    out = ev.attach_calendar(frame)
    assert out["calendar_flag"].tolist() == ["nfp-2026-10-02", ""]


def test_a_felulet_formaja():
    assert _calendar({"horizon": 5})["status"] == "not_collected"
    shown = _calendar({"calendar_flag": "nfp-2026-10-02", "target_session": date(2026, 10, 2)})
    assert shown["status"] == "ok"
    assert shown["events"] == [
        {"id": "nfp-2026-10-02", "kind": "nfp", "day": "2026-10-02", "time_et": "08:30"}
    ]
    assert shown["uncovered"] == []
    # 2027-ben a CPI és az NFP még nincs közzétéve: ezt ki kell mondani
    late = _calendar({"calendar_flag": "", "target_session": date(2027, 1, 20)})
    assert late["uncovered"] == ["cpi", "nfp"]
