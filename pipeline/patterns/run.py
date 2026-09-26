"""A minta-aréna teljes historikus mérése (spec/03 3.3; spec/08).

Minden papíron időrendben: támasz-ellenállás (M7), gyertyaminták (M2),
váll-fej-váll (M3). Az eseményeket ugyanaz a kód méri, mint az
indikátor-arénát — ugyanazzal a baseline-nal, effektív mintaszámmal és
FDR-korrekcióval, ami itt a teljes minta-családra megy.

A bontások a spec szerint:
  - gyertyaminták: szinten (`at_level`) és nem szinten (`none`), külön
  - támasz-ellenállás: hányadik érintés, és friss vagy régi szint
  - váll-fej-váll: a négy érvényességi állapot, külön

Futtatás:
    uv run python -m pipeline.patterns.run
    uv run python -m pipeline.patterns.run --local data --dry-run
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from pipeline import log as logging_setup
from pipeline.arena.evaluate import HORIZONS, arena
from pipeline.config import HISTORY_START, RAW_BUCKET, load_settings
from pipeline.features.run import _load_prices
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.patterns import candles, headshoulders
from pipeline.patterns.levels import touch_bucket, walk_levels
from pipeline.publish.run import DISPLAY_BUCKET
from pipeline.universe import active_on, load_universe

log = logging_setup.get_logger(__name__)

RESULTS_PATH = "arena/patterns.parquet"
DISPLAY_FILE = "pattern-arena.json"

SR_DIRECTIONS = {"sr_support_touch": "long", "sr_resistance_touch": "short"}


def instrument_events(instrument: str, frame: pd.DataFrame) -> list[dict[str, object]]:
    """Egy papír összes minta-eseménye, a bontásokkal együtt.

    Egy esemény több sorban is megjelenhet: egyszer az összesítésben (pl.
    `hammer`), egyszer a bontásban (pl. `hammer|at_level`). A két sor más
    kérdésre felel, és külön mérődik.
    """
    data = frame.sort_values("date").reset_index(drop=True)
    dates = data["date"].to_numpy()
    rows: list[dict[str, object]] = []

    def add(day: int, rule: str, direction: str) -> None:
        rows.append({"instrument_id": instrument, "date": dates[day], "rule": rule, "direction": direction})

    walk = walk_levels(data)
    for day, rule, number, fresh in walk.touches:
        direction = SR_DIRECTIONS[rule]
        add(day, rule, direction)
        add(day, f"{rule}|touch_{touch_bucket(number)}", direction)
        add(day, f"{rule}|{'fresh' if fresh else 'old'}", direction)

    for day, name, context in candles.events(data, walk):
        direction = candles.PATTERNS[name][0]
        add(day, name, direction)
        add(day, f"{name}|{context}", direction)

    for day, name, state, direction in headshoulders.events(data):
        add(day, f"{name}|{state}", direction)

    return rows


def directions_of(signals: pd.DataFrame) -> dict[str, str]:
    """Szabály → irány. Egy szabályazonosítónak egyetlen iránya lehet."""
    pairs = signals[["rule", "direction"]].drop_duplicates()
    duplicated = pairs["rule"].duplicated()
    if duplicated.any():
        raise RuntimeError(f"Kétirányú szabály: {sorted(pairs.loc[duplicated, 'rule'])}")
    return dict(zip(pairs["rule"], pairs["direction"], strict=True))


def _events_of(item: tuple[str, pd.DataFrame]) -> list[dict[str, object]]:
    return instrument_events(*item)


def build(prices: pd.DataFrame, workers: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Az összes esemény és a mérés.

    A szint-bejárás szándékosan napról napra halad (így nem nézhet a
    jövőbe), ezért egy magon 620 papír húsz éve kb. két óra. A papírok
    viszont függetlenek egymástól: párhuzamosan számolódnak. Az eredmény
    ugyanaz, mintha egymás után futnának — a sorrend a papír azonosítója.
    """
    groups = [(str(i), g) for i, g in prices.groupby("instrument_id", sort=True)]
    rows: list[dict[str, object]] = []
    if workers == 1 or len(groups) < 8:
        for item in groups:
            rows.extend(_events_of(item))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for part in pool.map(_events_of, groups, chunksize=4):
                rows.extend(part)
    signals = pd.DataFrame(rows, columns=["instrument_id", "date", "rule", "direction"])
    if signals.empty:
        return signals, pd.DataFrame()
    results = arena(signals, prices, directions_of(signals))
    return signals, results


def display_payload(results: pd.DataFrame, signals: pd.DataFrame, now: datetime) -> dict[str, object]:
    rows = []
    for row in results.to_dict("records"):
        rule = str(row["rule"])
        base, _, variant = rule.partition("|")
        rows.append(
            {
                "rule": rule,
                "pattern": base,
                "variant": variant or "all",
                "direction": row["direction"],
                "horizon": int(row["horizon"]),
                "hit_rate": round(float(row["value"]), 4),
                "baseline": round(float(row["baseline_value"]), 4),
                "delta": round(float(row["delta"]), 4),
                "n": int(row["n"]),
                "n_eff": round(float(row["n_eff"]), 1),
                "p_value": round(float(row["p_value"]), 4),
                "verdict": row["verdict"],
            }
        )
    dates = pd.to_datetime(signals["date"]) if not signals.empty else pd.Series(dtype="datetime64[ns]")
    return {
        "generated_at": now.astimezone(UTC).replace(microsecond=0).isoformat(),
        "horizons": list(HORIZONS),
        "measured_from": None if dates.empty else str(dates.min().date()),
        "measured_to": None if dates.empty else str(dates.max().date()),
        "events_total": len(signals),
        "instruments": int(signals["instrument_id"].nunique()) if not signals.empty else 0,
        "survivorship_bias": True,
        "synonyms": candles.SYNONYMS,
        "low_reliability": sorted(candles.LOW_RELIABILITY),
        "rows": rows,
    }


def run(storage: Storage, now: datetime, dry_run: bool = False) -> dict[str, object]:
    prices = _load_prices(storage, list(range(HISTORY_START.year, now.year + 1)))
    if prices.empty:
        raise RuntimeError("Nincs árfolyam a tárban — előbb az ingest fusson le.")
    universe = active_on(load_universe(), now.astimezone(UTC).date())
    prices = prices[prices["instrument_id"].isin(set(universe["instrument_id"]))].copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.date

    log.info("patterns_start", instruments=int(prices["instrument_id"].nunique()), rows=len(prices))
    signals, results = build(prices)
    payload = display_payload(results, signals, now)
    summary = {
        "events": len(signals),
        "rules": int(signals["rule"].nunique()) if not signals.empty else 0,
        "rows": len(results),
        "better_significant": int((results["verdict"] == "better_significant").sum())
        if not results.empty
        else 0,
        "worse": int((results["verdict"] == "worse").sum()) if not results.empty else 0,
    }
    if dry_run:
        log.info("patterns_dry_run", **summary)
        return {**summary, "status": "dry_run"}

    buffer = io.BytesIO()
    results.to_parquet(buffer, index=False, compression="zstd")
    storage.upload(RAW_BUCKET, RESULTS_PATH, buffer.getvalue(), "application/octet-stream")
    storage.upload(
        DISPLAY_BUCKET,
        DISPLAY_FILE,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
        "application/json",
    )
    log.info("patterns_done", **summary)
    return {**summary, "status": "saved"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Minta-aréna, teljes historikus mérés")
    parser.add_argument("--local", type=Path, default=None, help="helyi tár a Supabase helyett")
    parser.add_argument("--dry-run", action="store_true", help="számol, de nem ír")
    args = parser.parse_args()
    logging_setup.configure()
    storage: Storage
    if args.local is not None:
        storage = LocalStorage(args.local)
    else:
        settings = load_settings()
        storage = SupabaseStorage(settings.supabase_url or "", settings.supabase_secret_key or "")
    result = run(storage, datetime.now(UTC), dry_run=args.dry_run)
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
