"""Végponttól végpontig futás hamis forrással és helyi tárral."""

import json
from datetime import UTC, date, datetime

import pandas as pd

from pipeline.calendar import sessions_back
from pipeline.ingest import run as run_module
from pipeline.ingest.chain import ProviderChain
from pipeline.ingest.providers.base import BaseProvider, ProviderResult
from pipeline.ingest.storage import LocalStorage
from pipeline.universe import load_universe
from tests.conftest import price_rows

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


class Everything(BaseProvider):
    """Minden papírra ad sort, a kért időszak minden sessionjére."""

    name = "fake"
    rate_limit = BaseProvider.rate_limit

    def _fetch_chunk(self, tickers, start, end):
        days = [d for d in sessions_back(end, 15) if d >= start]
        frames = [price_rows(t, days) for t in tickers]
        # Az egyik papírnak a mai (még le nem zárt) napra is van sora — el kell dobni.
        frames.append(price_rows(tickers[0], [date(2026, 9, 21)]))
        return ProviderResult(pd.concat(frames), pd.DataFrame())


def test_backfill_then_daily_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(run_module, "build_chain", lambda: ProviderChain([Everything()]))
    storage = LocalStorage(tmp_path)

    first = run_module.run("backfill", storage, NOW)
    second = run_module.run("daily", storage, NOW)

    assert first["missing"] == []
    assert second["missing"] == []
    part = pd.read_parquet(tmp_path / "market-data-raw" / "prices_daily" / "year=2026.parquet")
    assert not part.duplicated(["instrument_id", "date"]).any()
    assert part["date"].max().isoformat() == "2026-09-18"  # a le nem zárt nap nem került be
    assert part["instrument_id"].nunique() == len(load_universe())


def test_summary_contains_counts_not_prices(tmp_path, monkeypatch):
    # A publikus repó naplója és összefoglalója nem tartalmazhat árat (spec/05, 1.).
    monkeypatch.setattr(run_module, "build_chain", lambda: ProviderChain([Everything()]))
    summary = run_module.run("daily", LocalStorage(tmp_path), NOW)
    text = json.dumps(summary)
    assert "close" not in text
    assert "adj_close" not in text
    assert all(not isinstance(v, float) for v in summary.values())
