"""A tézisek kiértékelése (docs/tezis-kiertekeles.md)."""

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from pipeline.calendar import sessions
from pipeline.journal import resolve as jr

DAYS = sessions(date(2026, 9, 1), date(2026, 10, 30))


def series(values: dict[date, float]) -> pd.Series:
    return pd.Series(values).sort_index()


def flat_then(start: date, end: date, start_price: float, end_price: float) -> pd.Series:
    """Egyenletes ár a kezdőnapig, utána a célár — csak a két végpont számít."""
    return series({d: (start_price if d <= start else end_price) for d in DAYS if d <= end})


def thesis(
    tid: str = "t1",
    direction: str = "long",
    p: float = 0.7,
    h: int = 5,
    created: datetime = datetime(2026, 9, 23, 19, 0, tzinfo=UTC),
    instrument: str = "CZ00001",
) -> jr.Thesis:
    return jr.Thesis(
        id=tid, instrument_id=instrument, direction=direction, probability=p, horizon=h, created_at=created
    )


class TestAblak:
    def test_napkozben_rogzitett_aznap_zarasatol_indul(self):
        # 15:00 New York-i idő
        assert jr.start_session(datetime(2026, 9, 23, 19, 0, tzinfo=UTC)) == date(2026, 9, 23)

    def test_pontosan_zaraskor_meg_aznap(self):
        assert jr.start_session(datetime(2026, 9, 23, 20, 0, tzinfo=UTC)) == date(2026, 9, 23)

    def test_zaras_utan_a_kovetkezo_nap(self):
        assert jr.start_session(datetime(2026, 9, 23, 20, 30, tzinfo=UTC)) == date(2026, 9, 24)

    def test_ejfel_utan_utc_szerint_de_new_yorkban_meg_elozo_este(self):
        # 2026-09-24 01:00 UTC = 09-23 21:00 New York: a 09-24-i zárás indít.
        assert jr.start_session(datetime(2026, 9, 24, 1, 0, tzinfo=UTC)) == date(2026, 9, 24)

    def test_hetvegen_rogzitett_hetfon_indul(self):
        assert jr.start_session(datetime(2026, 9, 26, 12, 0, tzinfo=UTC)) == date(2026, 9, 28)

    def test_idozona_nelkuli_ido_hiba(self):
        naive = datetime(2026, 9, 23, 19, 0, tzinfo=UTC).replace(tzinfo=None)
        with pytest.raises(ValueError, match="időzóna"):
            jr.start_session(naive)

    def test_celnap_kereskedesi_napokban(self):
        assert jr.target_session(date(2026, 9, 23), 5) == date(2026, 9, 30)


class TestPontozas:
    start, end = date(2026, 9, 23), date(2026, 9, 30)

    def test_long_talalat_es_brier(self):
        out, counts = jr.resolve_theses(
            [thesis()], {"CZ00001": flat_then(self.start, self.end, 100, 103)}, pd.DataFrame(), self.end
        )
        row = out["t1"]
        assert row["outcome_hit"] is True
        assert row["outcome_brier"] == pytest.approx(0.09)
        assert row["outcome_return"] == pytest.approx(0.03)
        assert row["start_session"] == "2026-09-23"
        assert row["target_session"] == "2026-09-30"
        assert row["resolution_type"] == "normal"
        assert "model_prob" not in row
        assert counts["no_model"] == 1

    def test_short_emelkedesnel_nem_talal(self):
        out, _ = jr.resolve_theses(
            [thesis(direction="short", p=0.6)],
            {"CZ00001": flat_then(self.start, self.end, 100, 101)},
            pd.DataFrame(),
            self.end,
        )
        assert out["t1"]["outcome_hit"] is False
        # p_up = 0,4, esemény = emelkedés → (0,4 − 1)² = 0,36
        assert out["t1"]["outcome_brier"] == pytest.approx(0.36)

    def test_valtozatlan_zaras_a_shortnak_talalat(self):
        # A modell szabálya: az esemény az y > 0; a nulla hozam „nem emelkedés”.
        out, _ = jr.resolve_theses(
            [thesis(direction="short", p=0.6)],
            {"CZ00001": flat_then(self.start, self.end, 100, 100)},
            pd.DataFrame(),
            self.end,
        )
        assert out["t1"]["outcome_hit"] is True

    def test_a_modell_es_a_baseline_ugyanarra_az_ablakra_a_tezis_iranyaba_forditva(self):
        forecasts = pd.DataFrame(
            [
                {
                    "instrument_id": "CZ00001",
                    "session": self.start,
                    "horizon": 5,
                    "prob_up": 0.58,
                    "baseline_prob": 0.53,
                }
            ]
        )
        out, _ = jr.resolve_theses(
            [thesis(direction="short", p=0.6)],
            {"CZ00001": flat_then(self.start, self.end, 100, 99)},
            forecasts,
            self.end,
        )
        row = out["t1"]
        assert row["model_prob"] == pytest.approx(0.42)
        assert row["baseline_prob"] == pytest.approx(0.47)
        # a modell emelkedést mondott, esett: nem talált; a Brier irányfüggetlen
        assert row["model_hit"] is False
        assert row["model_brier"] == pytest.approx(0.58**2)
        assert row["baseline_brier"] == pytest.approx(0.53**2)

    def test_meg_nem_jart_le(self):
        out, counts = jr.resolve_theses(
            [thesis()],
            {"CZ00001": flat_then(self.start, self.end, 100, 103)},
            pd.DataFrame(),
            date(2026, 9, 29),
        )
        assert out == {}
        assert counts["not_due"] == 1

    def test_nincs_ar_nem_talal_ki_eredmenyt(self):
        out, counts = jr.resolve_theses([thesis()], {}, pd.DataFrame(), self.end)
        assert out == {}
        assert counts["no_price"] == 1

    def test_kivezetett_papir_az_utolso_zarassal(self):
        cut = series({d: 100.0 if d <= self.start else 95.0 for d in DAYS if d <= date(2026, 9, 25)})
        out, _ = jr.resolve_theses([thesis()], {"CZ00001": cut}, pd.DataFrame(), self.end)
        assert out["t1"]["resolution_type"] == "delisted_or_halted"
        assert out["t1"]["outcome_hit"] is False


class FakeStore:
    def __init__(self, theses: list[jr.Thesis], fail: bool = False):
        self.theses, self.fail, self.written = theses, fail, {}

    def open_theses(self) -> list[jr.Thesis]:
        if self.fail:
            raise RuntimeError("journal_fetch_failed:503")
        return self.theses

    def write_outcome(self, thesis_id: str, outcome: dict[str, object]) -> bool:
        self.written[thesis_id] = outcome
        return True


def test_a_nyilvanos_naplo_csak_darabszamot_kap(monkeypatch):
    seen: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(jr.log, "info", lambda event, **kw: seen.append((event, kw)))
    start, end = date(2026, 9, 23), date(2026, 9, 30)
    store = FakeStore([thesis(tid="secret-id-1", instrument="CZ00042")])
    counts = jr.run(store, {"CZ00042": flat_then(start, end, 100, 103)}, pd.DataFrame(), end)
    assert counts["written"] == 1
    assert "secret-id-1" in store.written
    event, fields = seen[-1]
    assert event == "journal_resolve_done"
    assert all(isinstance(v, int) for v in fields.values())
    assert "secret-id-1" not in repr(seen)
    assert "CZ00042" not in repr(seen)


def test_a_tezisek_hibaja_nem_allitja_meg_a_becslesek_kiertekeleset(monkeypatch):
    from pipeline.resolve import run as resolve_run

    errors: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(resolve_run.log, "error", lambda event, **kw: errors.append((event, kw)))
    prices = pd.DataFrame({"instrument_id": ["CZ00001"], "date": [date(2026, 9, 23)], "close": [100.0]})
    actions = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])
    result = resolve_run.resolve_journal(
        FakeStore([], fail=True), prices, actions, pd.DataFrame(), date(2026, 9, 30)
    )
    assert result is None
    # csak a hiba típusa, az üzenete nem
    assert errors == [("journal_resolve_failed", {"error": "RuntimeError"})]


def test_kripto_ablak_a_rogzites_utc_napja_plusz_h_nap():
    """`docs/tezis-kiertekeles.md`, 10.: ugyanaz, mint a 0022-es adatbázis-szabály."""
    from datetime import UTC, date, datetime

    from pipeline.journal.resolve import start_session, target_session

    # Szombat késő este (UTC) rögzítve: aznap indul, nincs hétvégi ugrás.
    s = start_session(datetime(2026, 10, 3, 23, 59, tzinfo=UTC), "24/7")
    assert s == date(2026, 10, 3)
    assert target_session(s, 5, "24/7") == date(2026, 10, 8)
    # Éjfél után már a következő UTC-nap.
    assert start_session(datetime(2026, 10, 4, 0, 0, 1, tzinfo=UTC), "24/7") == date(2026, 10, 4)


def test_deviza_ablak_a_fixalashoz_igazodik():
    """`docs/tezis-kiertekeles.md`, 11.: ugyanaz, mint a 0024-es adatbázis-szabály."""
    from datetime import UTC, date, datetime

    from pipeline.journal.resolve import start_session, target_session

    # A fixálás (12:10 UTC, nyári idő) előtt rögzítve: aznap indul.
    assert start_session(datetime(2026, 10, 2, 11, 0, tzinfo=UTC), "TARGET") == date(2026, 10, 2)
    # Utána: a következő TARGET-nap (hétfő).
    s = start_session(datetime(2026, 10, 2, 12, 30, tzinfo=UTC), "TARGET")
    assert s == date(2026, 10, 5)
    assert target_session(s, 5, "TARGET") == date(2026, 10, 12)
