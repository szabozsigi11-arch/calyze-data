from datetime import date

import numpy as np
import pandas as pd

from pipeline.macro import align_to_sessions


def raw(values: dict[date, float]) -> pd.DataFrame:
    idx = list(values)
    return pd.DataFrame(
        {
            "vix": list(values.values()),
            "yield_10y": [4.0] * len(idx),
            "yield_2y": [3.5] * len(idx),
            "yield_3m": [5.0] * len(idx),
            "dollar_index": [120.0] * len(idx),
        },
        index=idx,
    )


def test_value_of_day_t_is_only_visible_from_t_plus_1():
    r = raw({date(2026, 9, 16): 15.0, date(2026, 9, 17): 25.0, date(2026, 9, 18): 30.0})
    out = align_to_sessions(r, date(2026, 9, 16), date(2026, 9, 18))
    assert np.isnan(out.loc[date(2026, 9, 16), "vix"])
    assert out.loc[date(2026, 9, 17), "vix"] == 15.0
    assert out.loc[date(2026, 9, 18), "vix"] == 25.0  # a 30-as érték még nem látszik


def test_no_backfill_and_forward_fill_is_limited():
    r = raw({date(2026, 8, 3): 20.0})
    out = align_to_sessions(r, date(2026, 7, 27), date(2026, 8, 31))
    assert out.loc[: date(2026, 8, 3), "vix"].isna().all()  # visszafelé nem töltünk
    filled = out["vix"].dropna()
    # Az eredeti megfigyelés + legfeljebb 5 előre töltött session, egy session késleltetéssel.
    assert len(filled) == 1 + 5
    assert filled.index[0] == date(2026, 8, 4)


def test_yield_curve_is_derived():
    r = raw({date(2026, 9, 16): 15.0, date(2026, 9, 17): 16.0})
    out = align_to_sessions(r, date(2026, 9, 16), date(2026, 9, 17))
    assert out.loc[date(2026, 9, 17), "yield_curve_10y2y"] == 0.5
