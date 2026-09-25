"""Az indikátor-aréna teljes historikus futása (spec/11, Fázis 2; N2).

Ez a futás minden szabályt végigmér az egész elérhető történeten, rezsim
szerinti bontással együtt. Hetekig tartó dolog nincs benne, de a gépen
(8 GB) így is szűk: ezért fut az Actionsben.

A kimenet két helyre megy:
  - a teljes táblázat a privát tárba (`arena/indicators.parquet`),
  - a megjelenítésre szánt JSON a `display` tárolóba, ahonnan a belépett
    felhasználó tölti le.

A nyers jelzés-táblát is elmentjük: így egy későbbi kérdésre („hány jelzés
volt 2014-ben?") nem kell újraszámolni mindent.

Futtatás:
    uv run python -m pipeline.arena.run
    uv run python -m pipeline.arena.run --local data --dry-run
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from pipeline import log as logging_setup
from pipeline.arena.evaluate import HORIZONS, arena
from pipeline.arena.signals import all_signals
from pipeline.config import HISTORY_START, RAW_BUCKET, load_settings
from pipeline.features.run import REGIME_PATH, _load_prices, _read_table
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.publish.run import DISPLAY_BUCKET
from pipeline.universe import active_on, load_universe

log = logging_setup.get_logger(__name__)

SIGNALS_PATH = "arena/signals.parquet"
RESULTS_PATH = "arena/indicators.parquet"
DISPLAY_FILE = "indicator-arena.json"


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False, compression="zstd")
    return buffer.getvalue()


def with_regime(signals: pd.DataFrame, regime: pd.DataFrame | None) -> pd.DataFrame:
    """A jelzés napjának rezsimje. Ahol nincs címke, ott `None` marad."""
    if regime is None or regime.empty:
        return signals.assign(regime=None)
    labels = regime[["date", "regime"]].copy()
    labels["date"] = pd.to_datetime(labels["date"]).dt.date
    merged = signals.copy()
    merged["date"] = pd.to_datetime(merged["date"]).dt.date
    return merged.merge(labels, on="date", how="left")


def build_tables(prices: pd.DataFrame, regime: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A jelzés-tábla és az aréna-táblázat (összesítve és rezsimenként)."""
    signals = with_regime(all_signals(prices), regime)

    overall = arena(signals, prices).assign(regime="all")
    parts = [overall]

    # Rezsimenként külön: a spec szerint a felület rezsim-szűrőt kap, és az
    # csak akkor őszinte, ha a mintaszám is rezsimenként számolódik.
    for label in sorted({r for r in signals["regime"].dropna().unique()}):
        subset = signals[signals["regime"] == label]
        table = arena(subset, prices)
        if not table.empty:
            parts.append(table.assign(regime=label))

    return signals, pd.concat(parts, ignore_index=True)


def display_payload(results: pd.DataFrame, signals: pd.DataFrame, now: datetime) -> dict[str, object]:
    """A felületnek szánt csomag. Ami nem mérhető, az nem kerül bele."""
    rows = []
    for row in results.to_dict("records"):
        rows.append(
            {
                "rule": row["rule"],
                "direction": row["direction"],
                "horizon": int(row["horizon"]),
                "regime": row["regime"],
                "hit_rate": round(float(row["value"]), 4),
                "baseline": round(float(row["baseline_value"]), 4),
                "delta": round(float(row["delta"]), 4),
                "n": int(row["n"]),
                "n_eff": round(float(row["n_eff"]), 1),
                "p_value": round(float(row["p_value"]), 4),
                "verdict": row["verdict"],
            }
        )
    first = pd.to_datetime(signals["date"]).min() if not signals.empty else None
    last = pd.to_datetime(signals["date"]).max() if not signals.empty else None
    return {
        "generated_at": now.astimezone(UTC).replace(microsecond=0).isoformat(),
        "horizons": list(HORIZONS),
        "measured_from": None if first is None else str(first.date()),
        "measured_to": None if last is None else str(last.date()),
        "signals_total": len(signals),
        # A túlélési torzítás nem lábjegyzet: a csomag maga hordozza, hogy a
        # felület soha ne tudja elhallgatni (`docs/jelzes-definiciok.md`).
        "survivorship_bias": True,
        "rows": rows,
    }


def run(storage: Storage, now: datetime, dry_run: bool = False) -> dict[str, object]:
    years = list(range(HISTORY_START.year, now.year + 1))
    prices = _load_prices(storage, years)
    if prices.empty:
        raise RuntimeError("Nincs árfolyam a tárban — előbb az ingest fusson le.")

    universe = active_on(load_universe(), now.astimezone(UTC).date())
    prices = prices[prices["instrument_id"].isin(set(universe["instrument_id"]))].copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.date

    log.info(
        "arena_start",
        instruments=int(prices["instrument_id"].nunique()),
        rows=len(prices),
        first=str(prices["date"].min()),
        last=str(prices["date"].max()),
    )

    regime = _read_table(storage, REGIME_PATH)
    signals, results = build_tables(prices, regime)
    payload = display_payload(results, signals, now)

    summary = {
        "signals": len(signals),
        "rows": len(results),
        "instruments": int(prices["instrument_id"].nunique()),
        "measured_from": payload["measured_from"],
        "measured_to": payload["measured_to"],
        "better_significant": int((results["verdict"] == "better_significant").sum()),
        "worse": int((results["verdict"] == "worse").sum()),
        "too_early": int((results["verdict"] == "too_early").sum()),
    }

    if dry_run:
        log.info("arena_dry_run", **summary)
        return {**summary, "status": "dry_run"}

    storage.upload(RAW_BUCKET, SIGNALS_PATH, _parquet_bytes(signals), "application/octet-stream")
    storage.upload(RAW_BUCKET, RESULTS_PATH, _parquet_bytes(results), "application/octet-stream")
    storage.upload(
        DISPLAY_BUCKET,
        DISPLAY_FILE,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
        "application/json",
    )
    storage.upload(
        RAW_BUCKET,
        f"runs/arena/{now.astimezone(UTC).date().isoformat()}.json",
        json.dumps(summary, indent=2, default=str).encode(),
        "application/json",
    )
    log.info("arena_done", **summary)
    return {**summary, "status": "saved"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Indikátor-aréna, teljes historikus futás")
    parser.add_argument("--local", type=Path, default=None, help="helyi tár a Supabase helyett")
    parser.add_argument("--dry-run", action="store_true", help="számol, de nem ír")
    args = parser.parse_args()

    logging_setup.setup()
    storage: Storage
    if args.local is not None:
        storage = LocalStorage(args.local)
    else:
        settings = load_settings()
        storage = SupabaseStorage(settings.supabase_url, settings.service_role_key)

    result = run(storage, datetime.now(UTC), dry_run=args.dry_run)
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
