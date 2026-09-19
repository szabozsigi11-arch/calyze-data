from datetime import UTC, date, datetime

import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

from pipeline.ingest.partitions import PRICE_SCHEMA, from_parquet, to_parquet, upsert


def rows(pairs, close=1.0):
    return pd.DataFrame(
        [
            {
                "instrument_id": i,
                "date": d,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "adj_close": close,
                "volume": 1.0,
                "source": "yfinance",
                "fetched_at": pd.Timestamp(datetime(2026, 9, 19, tzinfo=UTC)),
                "quality": "ok",
            }
            for i, d in pairs
        ]
    )


def test_fresh_rows_overwrite_same_key():
    old = rows([("CZ00001", date(2026, 9, 17)), ("CZ00001", date(2026, 9, 18))], close=1.0)
    new = rows([("CZ00001", date(2026, 9, 18))], close=2.0)
    out = upsert(old, new)
    assert len(out) == 2
    assert out.loc[out["date"] == date(2026, 9, 18), "close"].item() == 2.0


def test_replaced_instrument_loses_all_old_rows():
    old = rows([("CZ00001", date(2026, 9, 16)), ("CZ00002", date(2026, 9, 16))])
    new = rows([("CZ00001", date(2026, 9, 18))])
    out = upsert(old, new, replace_ids=["CZ00001"])
    assert set(zip(out["instrument_id"], out["date"], strict=True)) == {
        ("CZ00001", date(2026, 9, 18)),
        ("CZ00002", date(2026, 9, 16)),
    }


def test_parquet_roundtrip_keeps_schema():
    f = rows([("CZ00001", date(2026, 9, 18))])
    back = from_parquet(to_parquet(f, PRICE_SCHEMA))
    assert list(back.columns) == PRICE_SCHEMA.names
    assert back["date"].iloc[0] == date(2026, 9, 18)


keys = st.lists(
    st.tuples(
        st.sampled_from(["CZ00001", "CZ00002", "CZ00003"]), st.dates(date(2026, 1, 1), date(2026, 1, 20))
    ),
    max_size=30,
)


@given(old=keys, new=keys)
def test_upsert_never_duplicates_and_keeps_every_fresh_row(old, new):
    old_f, new_f = rows(sorted(set(old))), rows(sorted(set(new)), close=2.0)
    out = upsert(old_f, new_f) if not old_f.empty else upsert(rows([]).reindex(columns=new_f.columns), new_f)
    assert not out.duplicated(["instrument_id", "date"]).any()
    for i, d in set(new):
        assert out.loc[(out["instrument_id"] == i) & (out["date"] == d), "close"].item() == 2.0
