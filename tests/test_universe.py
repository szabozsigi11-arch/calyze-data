from datetime import date

import pandas as pd
import pytest

from pipeline.universe import UniverseError, active_on, load_universe, validate_universe


def test_universe_size_and_segments():
    u = load_universe()
    assert len(u) == 620
    assert u["segment"].value_counts().to_dict() == {"sp500": 500, "midcap": 100, "etf": 20}
    assert u["instrument_id"].is_unique
    # Az azonosítók folytonosak: újat mindig a végére veszünk fel, régit soha nem adunk ki újra.
    assert list(u["instrument_id"]) == [f"CZ{i:05d}" for i in range(1, len(u) + 1)]


def test_first_100_ids_never_change():
    # A 0. fázisban kiadott azonosítók lenyomata: ha bármelyik ticker-azonosító pár
    # megváltozna, a már lementett adatok rossz papírhoz kötődnének.
    import hashlib

    head = load_universe().head(100)
    digest = hashlib.sha256(",".join(head["instrument_id"] + ":" + head["ticker"]).encode()).hexdigest()
    assert digest == "a2317dc0eee324d2af5e836f2ce4ff717122f85ec27d44c9971dfdf91310dfa3"


def test_share_class_duplicates_are_excluded():
    tickers = set(load_universe()["ticker"])
    assert "GOOGL" in tickers
    assert not {"GOOG", "FOX", "NWS"} & tickers


def test_every_gics_sector_is_covered():
    u = load_universe()
    sectors = set(u.loc[u["asset_class"] == "equity", "sector"])
    assert len(sectors) == 11


def test_shock_detector_basket_is_in_universe():
    # spec/05, 9. fejezet, 4. sor: részvényindex, arany, olaj, dollár, hosszú kötvény.
    tickers = set(load_universe()["ticker"])
    assert {"SPY", "GLD", "USO", "UUP", "TLT"} <= tickers


def test_active_on_respects_validity_window():
    u = load_universe()
    assert len(active_on(u, date(2026, 9, 19))) == 620
    assert len(active_on(u, date(2026, 9, 18))) == 0


def test_duplicate_active_ticker_is_rejected():
    u = pd.read_csv("pipeline/universe/instruments.csv", dtype=str, keep_default_na=False)
    bad = pd.concat([u, u.iloc[[0]].assign(instrument_id="CZ99999")])
    with pytest.raises(UniverseError):
        validate_universe(bad)
