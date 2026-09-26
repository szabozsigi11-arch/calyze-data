"""A piac-implikált valószínűség: ismert válaszú, kitalált láncokon."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd

from pipeline.options.implied import choose_expiry, implied_from_chain


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_call(spot: float, strike: float, years: float, rate: float, vol: float) -> float:
    d1 = (math.log(spot / strike) + (rate + vol * vol / 2) * years) / (vol * math.sqrt(years))
    d2 = d1 - vol * math.sqrt(years)
    return spot * norm_cdf(d1) - strike * math.exp(-rate * years) * norm_cdf(d2)


SESSION = date(2026, 9, 25)
EXPIRY = date(2026, 10, 23)  # 28 naptári nap
YEARS = (EXPIRY - SESSION).days / 365


def chain(
    spot: float, rate: float, vol_at, step: float = 1.0, spread: float = 0.01, oi: int = 500
) -> pd.DataFrame:
    rows = []
    for k in [spot + step * i for i in range(-10, 11)]:
        vol = vol_at(k)
        price = bs_call(spot, k, YEARS, rate, vol)
        rows.append(
            {
                "strike": k,
                "bid": price - spread / 2,
                "ask": price + spread / 2,
                "impliedVolatility": vol,
                "openInterest": oi,
            }
        )
    return pd.DataFrame(rows)


def test_lapos_volatilitasnal_visszaadja_az_ismert_valaszt() -> None:
    """Lapos volatilitás mellett a digitális közelítés ≈ N(d2) a pár felezőpontján."""
    spot, rate, vol = 100.0, 0.04, 0.25
    result = implied_from_chain(
        chain(spot, rate, lambda _k: vol, step=0.5), spot + 0.25, SESSION, EXPIRY, rate, 20
    )
    assert result.status == "ok"
    k_bar = spot + 0.25
    d2 = (math.log((spot) / k_bar) + (rate - vol * vol / 2) * YEARS) / (vol * math.sqrt(YEARS))
    assert abs(result.prob_up - norm_cdf(d2)) < 0.005


def test_a_ferdeseget_is_latja() -> None:
    """Ha a volatilitás a kötési árral csökken (a szokásos részvény-ferdeség),
    a digitális valószínűség MAGASABB a lapos képletnél. Pont ezt veszítené el
    az egyetlen volatilitásos számítás."""
    spot, rate = 100.0, 0.04
    flat = implied_from_chain(chain(spot, rate, lambda _k: 0.25), spot, SESSION, EXPIRY, rate, 20)
    skew = implied_from_chain(
        chain(spot, rate, lambda k: 0.25 - 0.004 * (k - spot)), spot, SESSION, EXPIRY, rate, 20
    )
    assert skew.prob_up > flat.prob_up + 0.02


def test_a_szeles_szoras_nem_megbizhato() -> None:
    spot, rate = 100.0, 0.04
    wide = chain(spot, rate, lambda _k: 0.25, spread=3.0)
    assert implied_from_chain(wide, spot, SESSION, EXPIRY, rate, 20).status == "illiquid"


def test_keves_nyitott_pozicio_nem_megbizhato() -> None:
    spot, rate = 100.0, 0.04
    thin = chain(spot, rate, lambda _k: 0.25, oi=20)
    assert implied_from_chain(thin, spot, SESSION, EXPIRY, rate, 20).status == "illiquid"


def test_a_lehetetlen_ar_nem_valoszinuseg() -> None:
    """Ha a magasabb kötési árú call drágább, a közelítés negatív — az rossz ár."""
    bad = pd.DataFrame(
        [
            {"strike": 99.0, "bid": 2.0, "ask": 2.02, "impliedVolatility": 0.25, "openInterest": 500},
            {"strike": 101.0, "bid": 3.0, "ask": 3.02, "impliedVolatility": 0.25, "openInterest": 500},
        ]
    )
    assert implied_from_chain(bad, 100.0, SESSION, EXPIRY, 0.04, 20).status == "bad_price"


def test_az_implikalt_sav_a_mi_savunkkal_azonos_alaku() -> None:
    spot, rate, vol = 100.0, 0.04, 0.30
    result = implied_from_chain(chain(spot, rate, lambda _k: vol), spot, SESSION, EXPIRY, rate, 20)
    t = 20 / 252
    assert result.band_high is not None
    assert result.band_low is not None
    assert abs((result.band_high - result.band_low) - 2 * 1.6448536 * vol * math.sqrt(t)) < 1e-6


def test_a_lejarat_a_turesen_belul_legkozelebbi() -> None:
    target = date(2026, 10, 23)
    expiries = [date(2026, 10, 16), date(2026, 10, 30), date(2026, 11, 20)]
    # 10-16 és 10-30 egyaránt 5 kereskedési napra van; a korábbi nyer.
    assert choose_expiry(expiries, target, 20) == date(2026, 10, 16)
    # Az 5 napos horizonton 2 nap a tűrés: 5 nap eltérés már túl sok.
    assert choose_expiry(expiries, target, 5) is None


class FakeTicker:
    """A forrás helyett: egy papír, aminek a láncát mi adjuk meg — vagy elhal."""

    def __init__(self, symbol: str) -> None:
        if symbol == "BROKEN":
            raise ConnectionError("a forrás nem válaszol")
        self.symbol = symbol
        self.options = () if symbol == "NOOPT" else ("2026-10-23",)

    def option_chain(self, _expiry: str):
        class Chain:
            calls = chain(100.0, 0.04, lambda _k: 0.25)

        return Chain()


def test_egy_elhalo_papir_nem_viszi_el_a_tobbit() -> None:
    from pipeline.options.fetch import fetch_implied

    result = fetch_implied(
        [("CZ1", "GOOD"), ("CZ2", "BROKEN"), ("CZ3", "NOOPT")],
        {"CZ1": 100.0, "CZ2": 100.0, "CZ3": 100.0},
        SESSION,
        {20: date(2026, 10, 23)},
        0.04,
        ticker_factory=FakeTicker,
    )
    status = dict(zip(result["instrument_id"], result["implied_status"], strict=True))
    assert status == {"CZ1": "ok", "CZ2": "fetch_failed", "CZ3": "no_chain"}


def test_kamat_nelkul_nincs_implikalt() -> None:
    from pipeline.options.fetch import fetch_implied

    result = fetch_implied(
        [("CZ1", "GOOD")], {"CZ1": 100.0}, SESSION, {20: date(2026, 10, 23)}, None, FakeTicker
    )
    assert list(result["implied_status"]) == ["no_rate"]


def test_ha_elfogy_az_ido_a_maradek_papir_sora_is_elkeszul() -> None:
    """A lassú forrás nem veheti el az időt a becsléstől."""
    from pipeline.options.fetch import fetch_implied

    ticks = iter([0.0, 0.0, 5.0, 11.0, 12.0])
    result = fetch_implied(
        [("CZ1", "GOOD"), ("CZ2", "GOOD"), ("CZ3", "GOOD")],
        {"CZ1": 100.0, "CZ2": 100.0, "CZ3": 100.0},
        SESSION,
        {20: date(2026, 10, 23)},
        0.04,
        ticker_factory=FakeTicker,
        budget_seconds=10,
        clock=lambda: next(ticks),
    )
    status = dict(zip(result["instrument_id"], result["implied_status"], strict=True))
    assert status == {"CZ1": "ok", "CZ2": "ok", "CZ3": "fetch_failed"}
