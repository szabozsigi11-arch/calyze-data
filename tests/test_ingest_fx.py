"""Deviza-letöltés: keresztárfolyam az EKB-ből, TARGET-napok, hiány jelölve."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from pipeline.fx.calendar import holidays, is_target_day, last_fixing_day, offset
from pipeline.ingest.fx import cross_rates, missing_days
from pipeline.universe import load_fx_universe


def test_target_unnepek_es_fixalas():
    assert date(2026, 4, 3) in holidays(2026)  # nagypéntek
    assert not is_target_day(date(2026, 12, 26))
    assert is_target_day(date(2026, 12, 24))
    assert offset(date(2026, 12, 22), 5) == date(2026, 12, 30)
    # A fixálás (12:10 UTC nyáron) előtt még az előző nap az utolsó.
    assert last_fixing_day(datetime(2026, 10, 2, 11, 0, tzinfo=UTC)) == date(2026, 10, 1)
    assert last_fixing_day(datetime(2026, 10, 2, 12, 30, tzinfo=UTC)) == date(2026, 10, 2)


def test_keresztarfolyam_az_euro_ellen_kozolt_ertekekbol():
    d = date(2026, 10, 1)
    ecb = pd.DataFrame(
        {
            "date": [d] * 7,
            "currency": ["USD", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD"],
            "per_eur": [1.10, 165.0, 0.85, 0.93, 1.65, 1.50, 1.80],
        }
    )
    out = cross_rates(ecb, load_fx_universe(), datetime(2026, 10, 1, 15, tzinfo=UTC))
    t = load_fx_universe().set_index("instrument_id")["ticker"]
    rate = out.assign(t=out["instrument_id"].map(t)).set_index("t")["close"]
    assert len(rate) == 28
    assert rate["EURUSD"] == pytest.approx(1.10)
    assert rate["USDJPY"] == pytest.approx(165.0 / 1.10)
    assert rate["GBPUSD"] == pytest.approx(1.10 / 0.85)
    assert rate["AUDNZD"] == pytest.approx(1.80 / 1.65)
    assert out["volume"].isna().all()
    assert (out["open"] == out["close"]).all()


def test_hianyzo_target_nap_jelolve():
    ecb = pd.DataFrame({"date": [date(2026, 9, 28), date(2026, 9, 30)], "currency": "USD", "per_eur": 1.1})
    assert missing_days(ecb, date(2026, 9, 28), date(2026, 9, 30)) == ["2026-09-29"]
