from datetime import date

import pandas as pd
import pytest

from pipeline.ingest.validate import ValidationError, check_hard_rules, drop_off_session, mark_quality


def frame(rows):
    return pd.DataFrame(rows, columns=["instrument_id", "date", "open", "high", "low", "close", "volume"])


def test_suspect_rows_are_marked_not_dropped():
    f = frame(
        [
            ("CZ00001", date(2026, 9, 17), 10, 11, 9, 10.5, 100),
            ("CZ00001", date(2026, 9, 18), 10, 9, 11, 10.5, 100),  # low > high
        ]
    )
    out = mark_quality(f)
    assert list(out["quality"]) == ["ok", "suspect"]
    assert len(out) == 2  # a gyanús sor nem tűnik el: lyuk nélkül marad az idősor


def test_future_rows_stop_the_run():
    f = frame([("CZ00001", date(2026, 9, 21), 10, 11, 9, 10.5, 100)])
    with pytest.raises(ValidationError, match="későbbi"):
        check_hard_rules(f, last_session=date(2026, 9, 18))


def test_duplicates_stop_the_run():
    row = ("CZ00001", date(2026, 9, 18), 10, 11, 9, 10.5, 100)
    with pytest.raises(ValidationError, match="ismétlődő"):
        check_hard_rules(frame([row, row]), last_session=date(2026, 9, 18))


def test_off_session_rows_are_dropped_and_counted():
    f = frame(
        [
            ("CZ00001", date(2026, 9, 18), 10, 11, 9, 10.5, 100),
            ("CZ00001", date(2026, 9, 19), 10, 11, 9, 10.5, 100),  # szombat
            ("CZ00001", date(2026, 11, 26), 10, 11, 9, 10.5, 100),  # hálaadás
        ]
    )
    kept, dropped = drop_off_session(f)
    assert dropped == 2
    assert list(kept["date"]) == [date(2026, 9, 18)]
