"""Megjelenítésre kész JSON-ok a webappnak (spec/03; spec/05, 1. fejezet).

A becslések parquetben, a privát tárban élnek; a felület nem lát oda, és nem
is olvashat parquetet. Ez a lépés a napi futás után átfordítja őket abba a
formába, amit a képernyők használnak, és egy **nem publikus** tárolóba
tölti fel, ahonnan csak belépett felhasználó tölthet le.

Ez tartja be az adatlicencet is: az ingyenes források adatát csak regisztrált
felhasználó láthatja, regisztrálni pedig egyelőre csak meghívókóddal lehet
(`docs/adatlicencek.md` a másik repóban).

Futtatás:
    uv run python -m pipeline.publish.run
    uv run python -m pipeline.publish.run --local data --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from pipeline import log as logging_setup
from pipeline.calendar import last_closed_session
from pipeline.config import RAW_BUCKET, load_settings
from pipeline.features.run import REGIME_PATH, _load_prices, _read_table
from pipeline.forecast.run import FORECAST_PREFIX
from pipeline.ingest.partitions import from_parquet
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.model.config import HORIZONS, MIN_HISTORY_SESSIONS
from pipeline.model.evaluate import MIN_OBSERVATIONS
from pipeline.resolve.run import LIVE_ARENA_PATH, load_outcomes
from pipeline.universe import active_on, load_universe

log = logging_setup.get_logger(__name__)

#: A megjelenítésre szánt tároló. Nem publikus: belépés nélkül nem olvasható.
DISPLAY_BUCKET = "display"

#: Ennyi kereskedési nap ára kerül a charthoz (spec/03, 2.1: 90–250 nap).
HISTORY_SESSIONS = 250

#: Ennyi napra visszamenőleg mutatjuk, hogyan változott a becslés.
TIMELINE_SESSIONS = 90


def _num(value: object, digits: int = 6) -> float | None:
    """Szám JSON-ba: a NaN nem szám, és nem is nulla — hiányzó értékként megy ki."""
    if value is None:
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) or math.isinf(out) else round(out, digits)


def _dumps(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")


def load_forecast_history(storage: Storage, years: list[int]) -> pd.DataFrame:
    frames = []
    for year in years:
        for path in storage.list(RAW_BUCKET, f"{FORECAST_PREFIX}/{year}"):
            blob = storage.download(RAW_BUCKET, path)
            if blob is not None:
                frames.append(from_parquet(blob))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["session", "instrument_id", "horizon"]).reset_index(drop=True)


def next_resolutions(forecasts: pd.DataFrame, outcomes: pd.DataFrame) -> dict[str, str | None]:
    """Horizontonként mikor zárul a legközelebbi még nyitott becslés.

    Ez adja a felület „mikorra várható” mondatát: mintaszám nélkül a dátum az
    egyetlen őszinte állítás, amit tenni tudunk.
    """
    done = set(outcomes["forecast_id"]) if not outcomes.empty else set()
    out: dict[str, str | None] = {}
    for horizon in HORIZONS:
        key = str(horizon)
        if forecasts.empty:
            out[key] = None
            continue
        part = forecasts[(forecasts["horizon"] == horizon) & (~forecasts["forecast_id"].isin(done))]
        targets = [t for t in part["target_session"].dropna().tolist()]
        out[key] = str(min(targets)) if targets else None
    return out


def build_arena(arena: pd.DataFrame) -> list[dict[str, object]]:
    """Az élő mérési rekordok. Ami 30 megfigyelés alatt van, az „too early”."""
    if arena.empty:
        return []
    records = []
    for row in arena.to_dict("records"):
        records.append(
            {
                "subject": row.get("subject_id"),
                "scope": row.get("scope"),
                "horizon": int(row["horizon"]),
                "regime": row.get("regime"),
                "metric": row.get("metric"),
                "baseline": row.get("baseline_id"),
                "value": _num(row.get("value")),
                "baseline_value": _num(row.get("baseline_value")),
                "delta": _num(row.get("delta")),
                "n": int(row.get("n") or 0),
                "n_eff": _num(row.get("n_eff"), 2),
                "p_value": _num(row.get("p_value")),
                "p_value_fdr": _num(row.get("p_value_fdr")),
                "n_tests": int(row.get("n_tests") or 0),
                "verdict": row.get("verdict"),
                "observations_needed": int(row["observations_needed"])
                if pd.notna(row.get("observations_needed"))
                else None,
                "first_observed": row.get("first_observed"),
                "last_observed": row.get("last_observed"),
            }
        )
    return records


def headline(records: list[dict[str, object]]) -> dict[str, object] | None:
    """A kumulált állás egy sorban: az irány-pontosság 20 napon, minden rezsimben."""
    for record in records:
        if record["metric"] == "direction_accuracy" and record["horizon"] == 20 and record["regime"] == "all":
            return record
    return records[0] if records else None


def build_latest(
    session: date,
    universe: pd.DataFrame,
    today_forecasts: pd.DataFrame,
    all_forecasts: pd.DataFrame,
    outcomes: pd.DataFrame,
    arena_records: list[dict[str, object]],
    regime: pd.DataFrame | None,
    now: datetime,
) -> dict[str, object]:
    resolved_recently = pd.DataFrame()
    if not outcomes.empty and "resolved_at" in outcomes:
        last_day = pd.to_datetime(outcomes["resolved_at"]).max()
        if pd.notna(last_day):
            resolved_recently = outcomes[pd.to_datetime(outcomes["resolved_at"]) == last_day]

    regime_label, regime_value = None, None
    if regime is not None and not regime.empty:
        row = regime[regime["date"] == session]
        if not row.empty:
            regime_label = str(row["regime"].iloc[0])
            # A „stress” a rezsim folytonos mérőszáma (0–1): a felület ezt
            # mutatja a címke mellett, hogy a határ közelsége is látszódjon.
            regime_value = _num(row["stress"].iloc[0]) if "stress" in row else None

    return {
        "session": str(session),
        "generated_at": now.astimezone(UTC).replace(microsecond=0).isoformat(),
        "regime": regime_label,
        "regime_stress": regime_value,
        "universe": len(universe),
        "instruments_with_forecast": int(today_forecasts["instrument_id"].nunique())
        if not today_forecasts.empty
        else 0,
        "forecasts_total": len(all_forecasts),
        "forecasts_open": int(len(all_forecasts) - len(outcomes)),
        "resolved": {
            "on": str(pd.to_datetime(resolved_recently["resolved_at"]).max().date())
            if not resolved_recently.empty
            else None,
            "count": len(resolved_recently),
            "hits": int(resolved_recently["hit"].sum()) if not resolved_recently.empty else 0,
            "baseline_hits": int(resolved_recently["baseline_hit"].sum())
            if not resolved_recently.empty
            else 0,
        },
        "verdict": headline(arena_records),
        "next_resolution": next_resolutions(all_forecasts, outcomes),
        "min_observations": MIN_OBSERVATIONS,
    }


def build_index(
    universe: pd.DataFrame, today_forecasts: pd.DataFrame, history: pd.DataFrame
) -> list[dict[str, object]]:
    """A kereséshez: minden papír, adatminőség-jelölővel (spec/02, F1, 2. lépés)."""
    covered = set(today_forecasts["instrument_id"]) if not today_forecasts.empty else set()
    counts = history.groupby("instrument_id")["date"].count().to_dict() if not history.empty else {}
    rows = []
    for row in universe.to_dict("records"):
        sessions = int(counts.get(row["instrument_id"], 0))
        rows.append(
            {
                "id": row["instrument_id"],
                "ticker": row["ticker"],
                "name": row["name"],
                "asset_class": row.get("asset_class"),
                "sector": row.get("sector"),
                "sessions": sessions,
                "forecastable": row["instrument_id"] in covered,
                # Ha nincs elég múlt, a felület halványítja a sort, és megmondja, miért.
                "reason": None
                if row["instrument_id"] in covered
                else ("short_history" if sessions < MIN_HISTORY_SESSIONS else "no_forecast"),
            }
        )
    return sorted(rows, key=lambda r: str(r["ticker"]))


def build_instrument(
    meta: dict[str, object],
    prices: pd.DataFrame,
    forecasts: pd.DataFrame,
    history: pd.DataFrame,
    outcomes: pd.DataFrame,
    session: date,
) -> dict[str, object]:
    """Egy papír teljes megjelenítési csomagja."""
    bars = prices.sort_values("date").tail(HISTORY_SESSIONS)
    candles = [
        {
            "d": str(row["date"]),
            "o": _num(row.get("open"), 4),
            "h": _num(row.get("high"), 4),
            "l": _num(row.get("low"), 4),
            "c": _num(row.get("close"), 4),
            "v": _num(row.get("volume"), 0),
        }
        for row in bars.to_dict("records")
    ]

    close = candles[-1]["c"] if candles else None
    previous = candles[-2]["c"] if len(candles) > 1 else None
    change = None
    if close is not None and previous not in (None, 0):
        change = _num(close / float(previous) - 1.0)

    horizons = []
    for row in forecasts.sort_values("horizon").to_dict("records"):
        raw = row.get("contributions")
        try:
            contributions = json.loads(raw) if isinstance(raw, str) and raw else []
        except json.JSONDecodeError:
            contributions = []
        horizons.append(
            {
                "horizon": int(row["horizon"]),
                "target_session": str(row["target_session"]) if pd.notna(row.get("target_session")) else None,
                "prob_up": _num(row.get("prob_up")),
                "baseline_prob": _num(row.get("baseline_prob")),
                "baseline": row.get("baseline_id"),
                "expected_return": _num(row.get("expected_return")),
                "band_low": _num(row.get("band_low")),
                "band_high": _num(row.get("band_high")),
                "price_low": _num(row.get("price_low"), 4),
                "price_high": _num(row.get("price_high"), 4),
                "expected_price": _num(row.get("expected_price"), 4),
                "made_at": str(row.get("made_at")),
                "contributions": contributions,
            }
        )

    timeline = [
        {
            "session": str(row["session"]),
            "horizon": int(row["horizon"]),
            "prob_up": _num(row.get("prob_up")),
            "band_low": _num(row.get("band_low")),
            "band_high": _num(row.get("band_high")),
        }
        for row in history.sort_values(["session", "horizon"]).to_dict("records")
    ]

    # A papírra szűrt élő teljesítmény: amíg nincs 30 lezárt megfigyelés,
    # csak a mintaszám megy ki — százalék nem (2. sarokkő).
    resolved = len(outcomes)
    performance = {
        "n": int(resolved),
        "min_observations": MIN_OBSERVATIONS,
        "hits": int(outcomes["hit"].sum()) if resolved else 0,
        "baseline_hits": int(outcomes["baseline_hit"].sum()) if resolved else 0,
    }

    return {
        "instrument": meta,
        "session": str(session),
        "close": close,
        "change": change,
        "regime": str(forecasts["regime"].iloc[0]) if not forecasts.empty and "regime" in forecasts else None,
        "candles": candles,
        "forecasts": horizons,
        "timeline": timeline,
        "performance": performance,
    }


def run(storage: Storage, now: datetime, dry_run: bool = False) -> dict[str, object]:
    session = last_closed_session(now)
    years = sorted({2026, session.year})

    all_forecasts = load_forecast_history(storage, years)
    if all_forecasts.empty:
        log.info("publish_nothing", reason="még nincs lementett becslés")
        return {"session": str(session), "instruments": 0, "status": "no_forecasts"}

    latest_session = max(all_forecasts["session"])
    today_forecasts = all_forecasts[all_forecasts["session"] == latest_session]
    outcomes = load_outcomes(storage, years)
    arena = _read_table(storage, LIVE_ARENA_PATH)
    arena_records = build_arena(arena if arena is not None else pd.DataFrame())

    # Az univerzum tagsága a MAI napra értendő, nem a becslés sessionjére: a
    # lista 2026-09-19-én készült, az első becslés viszont az előző napra szól,
    # és akkor minden papír kiesne a szűrőből.
    universe = active_on(load_universe(), now.astimezone(UTC).date())
    prices = _load_prices(storage, list(range(max(2005, latest_session.year - 2), latest_session.year + 1)))
    regime = _read_table(storage, REGIME_PATH)

    cutoff = pd.Timestamp(latest_session) - pd.Timedelta(days=TIMELINE_SESSIONS * 2)
    timeline_source = all_forecasts[pd.to_datetime(all_forecasts["session"]) >= cutoff]

    files: list[tuple[str, bytes]] = [
        (
            "latest.json",
            _dumps(
                build_latest(
                    latest_session,
                    universe,
                    today_forecasts,
                    all_forecasts,
                    outcomes,
                    arena_records,
                    regime,
                    now,
                )
            ),
        ),
        ("arena.json", _dumps(arena_records)),
        ("instruments.json", _dumps(build_index(universe, today_forecasts, prices))),
    ]

    by_instrument = {i: g for i, g in today_forecasts.groupby("instrument_id")}
    price_groups = {i: g for i, g in prices.groupby("instrument_id")}
    timeline_groups = {i: g for i, g in timeline_source.groupby("instrument_id")}
    outcome_groups = {i: g for i, g in outcomes.groupby("instrument_id")} if not outcomes.empty else {}

    written = 0
    for row in universe.to_dict("records"):
        instrument_id = str(row["instrument_id"])
        payload = build_instrument(
            meta={
                "id": instrument_id,
                "ticker": row["ticker"],
                "name": row["name"],
                "asset_class": row.get("asset_class"),
                "sector": row.get("sector"),
                "exchange_calendar": row.get("exchange_calendar"),
            },
            prices=price_groups.get(instrument_id, pd.DataFrame(columns=prices.columns)),
            forecasts=by_instrument.get(instrument_id, pd.DataFrame()),
            history=timeline_groups.get(instrument_id, pd.DataFrame(columns=["session", "horizon"])),
            outcomes=outcome_groups.get(instrument_id, pd.DataFrame()),
            session=latest_session,
        )
        files.append((f"instruments/{instrument_id}.json", _dumps(payload)))
        written += 1

    if dry_run:
        log.info("publish_dry_run", files=len(files), instruments=written)
        return {"session": str(latest_session), "instruments": written, "status": "dry_run"}

    storage.ensure_private_bucket(DISPLAY_BUCKET)
    for path, blob in files:
        storage.upload(DISPLAY_BUCKET, path, blob, "application/json")

    log.info("publish_done", session=str(latest_session), files=len(files))
    return {
        "session": str(latest_session),
        "instruments": written,
        "files": len(files),
        "status": "published",
    }


def main(argv: list[str] | None = None) -> int:
    logging_setup.configure()
    parser = argparse.ArgumentParser(description="Megjelenítési JSON-ok a webappnak")
    parser.add_argument("--local", type=Path, help="helyi tár (próbafuttatáshoz)")
    parser.add_argument("--dry-run", action="store_true", help="ne töltsön fel semmit")
    parser.add_argument("--out", type=Path, help="a JSON-ok mentése ide (próbafuttatáshoz)")
    args = parser.parse_args(argv)

    if args.local is not None:
        storage: Storage = LocalStorage(args.local)
    else:
        settings = load_settings()
        if not settings.storage_configured:
            print("Hiányzik a SUPABASE_URL vagy a SUPABASE_SECRET_KEY.", file=sys.stderr)
            return 2
        storage = SupabaseStorage(settings.supabase_url or "", settings.supabase_secret_key or "")

    result = run(storage, datetime.now(UTC), dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
