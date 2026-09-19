"""A spec/05 2.5 tesztesetei: felosztás, osztalék (teljes hozam), kivezetés, tickerváltás."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from pipeline.corporate import (
    adjust_user_price,
    detect_delisted,
    log_total_returns,
    split_factor,
    total_return_prices,
)
from pipeline.universe import load_ticker_history, load_universe, ticker_on

ACTIONS = pd.DataFrame(
    {
        "instrument_id": ["CZ00001", "CZ00001", "CZ00002"],
        "date": [date(2026, 6, 10), date(2026, 8, 3), date(2026, 6, 10)],
        "dividend": [0.0, 0.25, 0.0],
        "split_ratio": [4.0, 0.0, 2.0],
    }
)


def test_split_adjusts_user_price_and_keeps_the_original():
    # spec/05 2.5: „You entered 812.00; adjusted 203.00.”
    assert adjust_user_price(812.0, ACTIONS, "CZ00001", date(2026, 5, 1), date(2026, 9, 18)) == pytest.approx(
        203.0
    )


def test_split_before_entry_does_not_count():
    assert split_factor(ACTIONS, "CZ00001", date(2026, 6, 10), date(2026, 9, 18)) == 1.0


def test_reverse_split_multiplies_the_price():
    reverse = pd.DataFrame(
        {"instrument_id": ["X"], "date": [date(2026, 7, 1)], "dividend": [0.0], "split_ratio": [0.1]}
    )
    assert adjust_user_price(2.0, reverse, "X", date(2026, 6, 1), date(2026, 9, 1)) == pytest.approx(20.0)


def test_total_return_includes_dividends():
    # Az ár nem változik, de 1 dollár osztalék volt: a teljes hozam +1%.
    prices = pd.DataFrame(
        {
            "instrument_id": ["A", "A", "A"],
            "date": [date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)],
            "close": [100.0, 99.0, 99.0],
        }
    )
    actions = pd.DataFrame(
        {"instrument_id": ["A"], "date": [date(2026, 9, 17)], "dividend": [1.0], "split_ratio": [0.0]}
    )
    tr = total_return_prices(prices, actions)
    assert tr.iloc[0] == 1.0
    assert tr.iloc[-1] == pytest.approx(1.0)  # 99 + 1 osztalék = 100: a befektető nem veszített
    assert np.exp(log_total_returns(prices, actions).sum()) == pytest.approx(1.0)


def test_total_return_without_dividends_is_price_return():
    prices = pd.DataFrame(
        {"instrument_id": ["A", "A"], "date": [date(2026, 9, 17), date(2026, 9, 18)], "close": [100.0, 110.0]}
    )
    empty = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])
    assert total_return_prices(prices, empty).iloc[-1] == pytest.approx(1.1)


def test_total_return_survives_duplicate_row_labels():
    # Az évfájlok összefűzése után a sorindex ismétlődhet; ez nem boríthatja fel a számítást.
    a = pd.DataFrame({"instrument_id": ["A"], "date": [date(2025, 12, 31)], "close": [100.0]})
    b = pd.DataFrame({"instrument_id": ["A"], "date": [date(2026, 1, 2)], "close": [105.0]})
    prices = pd.concat([a, b])  # mindkét sor indexe 0
    empty = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])
    assert list(total_return_prices(prices, empty)) == pytest.approx([1.0, 1.05])


def test_delisted_instrument_is_detected_with_its_last_day():
    prices = pd.DataFrame(
        {
            "instrument_id": ["LIVE", "LIVE", "GONE"],
            "date": [date(2026, 9, 17), date(2026, 9, 18), date(2026, 9, 1)],
        }
    )
    assert detect_delisted(prices, date(2026, 9, 18)) == {"GONE": date(2026, 9, 1)}


def test_ticker_change_keeps_the_instrument_id(tmp_path):
    # FB → META: a 2021-es tézis FB-ként látszik, de ugyanahhoz az azonosítóhoz tartozik.
    history = tmp_path / "h.csv"
    history.write_text("instrument_id,ticker,valid_from,valid_to\nCZ00015,FB,2012-05-18,2022-06-08\n")
    u, h = load_universe(), load_ticker_history(history)
    assert ticker_on("CZ00015", date(2021, 3, 1), u, h) == "FB"
    assert ticker_on("CZ00015", date(2026, 9, 18), u, h) == "META"
