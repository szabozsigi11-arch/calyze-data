"""Kripto-arénák: indikátor, minta, hír (`docs/kripto-arenak.md`).

A szabályok és a mérés a részvényes arénák függvényei; itt csak a kripto
ára, rezsimje és a saját korrekciós családja kerül beléjük. Az eredmény a
`crypto/` megjelenítési mappába megy, a részvényes fájlokhoz nem nyúl.

Futtatás:
    uv run python -m pipeline.crypto.arenas
    uv run python -m pipeline.crypto.arenas --only indicators
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from pipeline import log as logging_setup
from pipeline.config import RAW_BUCKET, load_settings
from pipeline.crypto.features import EMPTY_ACTIONS, REGIME_BASKET, crypto_regime, load_crypto_prices
from pipeline.crypto.forecast import PREFIX as FORECAST_PREFIX
from pipeline.crypto.shocks import BROAD_MIN
from pipeline.features.run import _write_table
from pipeline.ingest.crypto import CRYPTO_HISTORY_START
from pipeline.ingest.partitions import from_parquet
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.model.evaluate import apply_fdr
from pipeline.newsarena.run import _record, measure_period
from pipeline.newsarena.signals import calendar_days, instrument_frame
from pipeline.publish.run import DISPLAY_BUCKET, build_news_arena
from pipeline.shocks.detect import CROSS_SIGMA, MOVE_SIGMA, VOLUME_Z
from pipeline.universe import active_on, load_crypto_universe

log = logging_setup.get_logger(__name__)

MARKET = "BTC-USD"
#: Az első élő kripto-becslés napja (docs/kripto-modell.md, 6.): eddig backtest.
LIVE_FROM = date(2026, 10, 2)


def _upload(storage: Storage, path: str, payload: object) -> None:
    storage.upload(
        DISPLAY_BUCKET,
        path,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode(),
        "application/json",
    )


def indicators(
    storage: Storage, prices: pd.DataFrame, regime: pd.DataFrame, now: datetime
) -> dict[str, object]:
    from pipeline.arena.run import build_tables, display_payload

    signals, results = build_tables(prices, regime)
    _write_table(storage, "arena/crypto_indicators.parquet", results)
    _upload(
        storage, "crypto/indicator-arena.json", {**display_payload(results, signals, now), "calendar": "24/7"}
    )
    return {
        "rows": len(results),
        "better_significant": int((results["verdict"] == "better_significant").sum()),
    }


def patterns(storage: Storage, prices: pd.DataFrame, now: datetime) -> dict[str, object]:
    from pipeline.patterns.run import build, display_payload

    signals, results = build(prices)
    if not results.empty:
        _write_table(storage, "arena/crypto_patterns.parquet", results)
    _upload(
        storage, "crypto/pattern-arena.json", {**display_payload(results, signals, now), "calendar": "24/7"}
    )
    return {
        "rows": len(results),
        "better_significant": int((results["verdict"] == "better_significant").sum())
        if not results.empty
        else 0,
    }


def crypto_frames(prices: pd.DataFrame, universe: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Papír-napok (rés-jel nélkül) és a BTC napjai a kosár-jellel (2. és 3. fejezet)."""
    inst = instrument_frame(prices, EMPTY_ACTIONS)
    inst["flag"] = inst["enough"] & ((inst["volume_z"] > VOLUME_Z) | (inst["move_sigma"] > MOVE_SIGMA))
    ids = universe.set_index("ticker")["instrument_id"]
    btc = inst[inst["instrument_id"] == ids[MARKET]].set_index("date").sort_index()
    market = pd.DataFrame(index=btc.index)
    market["sigma_before"] = btc["sigma_before"]
    market["vol_after"] = btc["vol_after"]
    moved = []
    for ticker in REGIME_BASKET:
        if ticker in ids.index:
            coin = inst[inst["instrument_id"] == ids[ticker]].set_index("date")
            moved.append(((coin["move_s60"] > CROSS_SIGMA) & coin["enough"]).rename(ticker))
    market["broad_count"] = pd.concat(moved, axis=1).reindex(market.index).fillna(False).sum(axis=1)
    market["market_flag"] = market["broad_count"] >= BROAD_MIN
    market["withheld"] = False
    return inst, market


def live_flags(
    storage: Storage, inst: pd.DataFrame, market: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Az élő időszak jelzései a lenyomatolt kripto-csomagokból (nem újraszámolva)."""
    frames = []
    for year in range(LIVE_FROM.year, datetime.now(UTC).year + 1):
        for path in storage.list(RAW_BUCKET, f"{FORECAST_PREFIX}/{year}"):
            blob = storage.download(RAW_BUCKET, path)
            if blob is not None:
                frames.append(from_parquet(blob))
    packages = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if packages.empty or "shock_signals" not in packages:
        return inst.iloc[0:0], market.iloc[0:0]
    packages = packages[packages["session"] >= LIVE_FROM]
    per = packages.drop_duplicates(["instrument_id", "session"])
    flags = {(r.instrument_id, r.session): bool(str(r.shock_signals or "")) for r in per.itertuples()}
    live_i = inst[[(i, d) in flags for i, d in zip(inst["instrument_id"], inst["date"], strict=True)]].copy()
    live_i["flag"] = [flags[(i, d)] for i, d in zip(live_i["instrument_id"], live_i["date"], strict=True)]
    per_day = packages.drop_duplicates("session").set_index("session")
    live_m = market[[d in per_day.index for d in market.index]].copy()
    live_m["market_flag"] = [bool(str(per_day.loc[d, "shock_market"] or "")) for d in live_m.index]
    live_m["withheld"] = False
    return live_i, live_m


def news(storage: Storage, prices: pd.DataFrame, universe: pd.DataFrame, now: datetime) -> dict[str, object]:
    inst, market = crypto_frames(prices, universe)
    first = date(2019, 1, 7)
    back_i = inst[(inst["date"] >= first) & (inst["date"] < LIVE_FROM)]
    back_m = market[[first <= d < LIVE_FROM for d in market.index]]
    calendar = calendar_days(sorted(market.index))
    rows = []
    for period, (i_part, m_part) in (
        ("backtest", (back_i, back_m)),
        ("live", live_flags(storage, inst, market)),
    ):
        part = measure_period(i_part, m_part, calendar, period)
        apply_fdr([c for _, c in part])
        rows += [{**_record(meta, c), "n_tests": len(part)} for meta, c in part]
    # A részvényes „market_shock” itt a kosár-jel: a felület más mondatot ír hozzá.
    table = pd.DataFrame(rows)
    if not table.empty:
        table["signal"] = table["signal"].replace({"market_shock": "crypto_broad"})
        _write_table(storage, "arena/crypto_news.parquet", table)
    payload = {**build_news_arena(table, now), "live_from": LIVE_FROM.isoformat(), "calendar": "24/7"}
    _upload(storage, "crypto/news-arena.json", payload)
    return {"records": len(table)}


def run(storage: Storage, now: datetime, only: str | None = None) -> dict[str, object]:
    universe = active_on(load_crypto_universe(), now.astimezone(UTC).date())
    prices = load_crypto_prices(storage, list(range(CRYPTO_HISTORY_START.year, now.year + 1)))
    prices = prices[prices["instrument_id"].isin(set(universe["instrument_id"]))].copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    regime = crypto_regime(prices, universe)
    summary: dict[str, object] = {}
    if only in (None, "indicators"):
        summary["indicators"] = indicators(storage, prices, regime, now)
    if only in (None, "news"):
        summary["news"] = news(storage, prices, universe, now)
    if only in (None, "patterns"):
        summary["patterns"] = patterns(storage, prices, now)
    log.info("crypto_arenas_done", **summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze kripto-arénák")
    parser.add_argument("--local", type=Path)
    parser.add_argument("--only", choices=["indicators", "patterns", "news"])
    args = parser.parse_args(argv)
    logging_setup.configure()
    if args.local:
        storage: Storage = LocalStorage(args.local)
    else:
        settings = load_settings()
        if not settings.supabase_url or not settings.supabase_secret_key:
            log.error("storage_not_configured")
            return 2
        storage = SupabaseStorage(settings.supabase_url, settings.supabase_secret_key)
    print(json.dumps(run(storage, datetime.now(UTC), args.only), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
