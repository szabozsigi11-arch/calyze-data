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


# ------------------------------------------------------------------ kripto (docs/kripto-univerzum.md)

#: A 2026-10-02-i kiválasztás lenyomata (azonosító : Yahoo-szimbólum).
DIGEST_CRYPTO = "062565fc954975d66baff074851f034c69ffcf3faa70141f5cc390d1b1e66c68"


def test_crypto_universe_is_separate_and_continues_the_ids():
    from pipeline.universe import load_crypto_universe

    c = load_crypto_universe()
    assert len(c) == 50
    assert set(c["asset_class"]) == {"crypto"}
    assert set(c["exchange_calendar"]) == {"24/7"}
    # A részvények után folytatódik, ütközés nélkül.
    assert list(c["instrument_id"]) == [f"CZ{i:05d}" for i in range(621, 671)]
    assert not set(c["instrument_id"]) & set(load_universe()["instrument_id"])
    # A részvényes futás továbbra sem lát kriptót.
    assert "crypto" not in set(load_universe()["asset_class"])


def test_crypto_ids_never_change():
    import hashlib

    from pipeline.universe import load_crypto_universe

    c = load_crypto_universe()
    digest = hashlib.sha256(",".join(c["instrument_id"] + ":" + c["source_symbol"]).encode()).hexdigest()
    assert c.iloc[0]["source_symbol"] == "BTC-USD"
    assert c.iloc[1]["source_symbol"] == "ETH-USD"
    assert digest == DIGEST_CRYPTO


def test_crypto_display_tickers_do_not_collide_with_equities():
    from pipeline.universe import load_crypto_universe

    assert not set(load_crypto_universe()["ticker"]) & set(load_universe()["ticker"])


def test_candidate_list_is_read_from_the_rule_document():
    from pipeline.universe.select_crypto import DOC, candidates_from_doc, display_ticker

    names = candidates_from_doc(DOC.read_text(encoding="utf-8"))
    assert names[:2] == ["Bitcoin", "Ethereum"]
    assert len(names) == len(set(names)) == 135
    assert display_ticker("UNI7083-USD") == "UNI-USD"
    assert display_ticker("1INCH-USD") == "1INCH-USD"


def test_symbol_resolution_needs_an_exact_name():
    from pipeline.universe.select_crypto import resolve

    quotes = [
        {"symbol": "GRAM-USD", "shortname": "Gram (prev. Toncoin) USD", "quoteType": "CRYPTOCURRENCY"},
        {"symbol": "TON11419-USD", "shortname": "Toncoin USD", "quoteType": "CRYPTOCURRENCY"},
        {"symbol": "TON", "shortname": "Toncoin USD", "quoteType": "EQUITY"},
    ]
    assert resolve("Toncoin", lambda _q: quotes) == "TON11419-USD"
    assert resolve("Mantle", lambda _q: quotes) is None


def test_fx_universe_28_pars_rule_and_ids():
    from pipeline.fx.universe import build
    from pipeline.universe import load_crypto_universe, load_fx_universe

    fx = load_fx_universe()
    assert len(fx) == 28
    assert list(fx["instrument_id"]) == [f"CZ{i:05d}" for i in range(671, 699)]
    # A fájl a szabályból áll elő: újragenerálva ugyanaz.
    assert list(build()["ticker"]) == list(fx["ticker"])
    assert {"EURUSD", "USDJPY", "GBPUSD", "AUDNZD", "CHFJPY"} <= set(fx["ticker"])
    taken = set(load_universe()["instrument_id"]) | set(load_crypto_universe()["instrument_id"])
    assert not set(fx["instrument_id"]) & taken
    assert not set(fx["ticker"]) & set(load_universe()["ticker"])
