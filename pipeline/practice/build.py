"""A kalibrációs edzés kérdésbankja (a privát repó `docs/terv-kalibracios-edzes.md`).

Vak, múltbeli ablakok: egy papír utolsó 120 napja **név, ticker és dátum
nélkül**, 100-ra normálva, és a folytatása. A felhasználó irányt és
valószínűséget mond, és azonnal látja, mi történt, a naiv baseline mellett.

A naiv baseline ugyanaz a szabály, mint a modellnél: az alapesély, de csak a
papír **saját, a kérdés napjáig ismert** múltjából (hány h napos ablakban
emelkedett). A jövőt nem látja.

Ez gyakorlás múltbeli adaton, nem rekord: a felület kimondja, és a
Bizonyíték-táblába nem számít bele.

Futtatás:
    uv run python -m pipeline.practice.build [--local data]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import log as logging_setup
from pipeline.config import load_settings
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage

log = logging_setup.get_logger(__name__)

DISPLAY_BUCKET = "display"
OUT_PATH = "practice/questions.json"
VERSION = "v1"
SEED = 20261020
WINDOW = 120
HORIZONS = (5, 20, 60)
#: Az eszközosztályok aránya a bankban; a kötvény kimarad (a hozam iránya fordított).
SHARES = {"equity": 0.5, "crypto": 0.25, "fx": 0.25}
QUESTIONS = 600
#: Legalább ennyi saját múltbeli ablak kell a baseline-hoz.
MIN_PAST_WINDOWS = 250
FIRST_DAY = date(2010, 1, 4)


def baseline_prob(series: np.ndarray, index: int, horizon: int) -> float | None:
    """Az addigi h napos ablakok emelkedési aránya; csak a kérdés napjáig lezártak."""
    past = series[: index + 1]
    if len(past) <= horizon + MIN_PAST_WINDOWS:
        return None
    rises = past[horizon:] > past[:-horizon]
    return float(np.clip(rises.mean(), 0.01, 0.99))


def question(series: np.ndarray, index: int, horizon: int, asset: str) -> dict[str, object] | None:
    if index < WINDOW or index + horizon >= len(series):
        return None
    base = baseline_prob(series, index, horizon)
    if base is None:
        return None
    anchor = series[index]
    before = series[index - WINDOW + 1 : index + 1] / anchor * 100
    after = series[index + 1 : index + horizon + 1] / anchor * 100
    if not (np.isfinite(before).all() and np.isfinite(after).all()):
        return None
    return {
        "asset": asset,
        "horizon": horizon,
        "closes": [round(float(v), 2) for v in before],
        "after": [round(float(v), 2) for v in after],
        "baseline_prob": round(base, 4),
        "up": bool(series[index + horizon] > anchor),
    }


def build(
    panels: dict[str, dict[str, pd.Series]], seed: int = SEED, n: int = QUESTIONS
) -> list[dict[str, object]]:
    """Kérdések eszközosztályonként a megadott arányban, rögzített véletlen maggal.

    `panels`: eszközosztály → papír → dátum szerint rendezett záró-idősor.
    """
    rng = np.random.default_rng(seed)
    out: list[dict[str, object]] = []
    for asset, share in SHARES.items():
        series_by_id = {
            k: v for k, v in panels.get(asset, {}).items() if len(v) > WINDOW + MIN_PAST_WINDOWS + 60
        }
        if not series_by_id:
            continue
        ids = sorted(series_by_id)
        want = round(n * share)
        tries = 0
        made = 0
        while made < want and tries < want * 20:
            tries += 1
            s = series_by_id[ids[int(rng.integers(len(ids)))]]
            horizon = int(HORIZONS[int(rng.integers(len(HORIZONS)))])
            days = np.asarray([pd.Timestamp(d).date() for d in s.index])
            first = int(np.searchsorted(days, FIRST_DAY))
            lo, hi = max(first, WINDOW + MIN_PAST_WINDOWS + horizon), len(s) - horizon - 1
            if hi <= lo:
                continue
            q = question(s.to_numpy(dtype="float64"), int(rng.integers(lo, hi)), horizon, asset)
            if q is None:
                continue
            out.append(q)
            made += 1
    # A sorrend keverve, az azonosító a tartalomból: a sorszám nem árulja el az eszközosztályt.
    order = rng.permutation(len(out))
    shuffled = [out[i] for i in order]
    for q in shuffled:
        q["id"] = hashlib.sha256(json.dumps(q, sort_keys=True).encode()).hexdigest()[:12]
    return shuffled


def panels_from_storage(storage: Storage, now: datetime) -> dict[str, dict[str, pd.Series]]:
    from pipeline.corporate import total_return_prices
    from pipeline.crypto.features import load_crypto_prices
    from pipeline.features.run import _load_prices, _read_table
    from pipeline.fx.features import load_fx_prices
    from pipeline.ingest.partitions import ACTIONS_PATH
    from pipeline.universe import load_fx_universe

    years = list(range(2005, now.year + 1))

    def by_id(frame: pd.DataFrame, column: str) -> dict[str, pd.Series]:
        frame = frame.assign(date=pd.to_datetime(frame["date"]).dt.date)
        return {
            str(i): g.set_index("date")[column].astype("float64").sort_index()
            for i, g in frame.groupby("instrument_id", sort=False)
        }

    equity = _load_prices(storage, years)
    actions = _read_table(storage, ACTIONS_PATH)
    if actions is None:
        actions = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])
    equity = equity.assign(tr=total_return_prices(equity, actions))
    fx = load_fx_prices(storage, years)
    # Csak a fő devizapárok: a keresztpár két másik pár különbsége.
    universe = load_fx_universe()
    main = set(universe.loc[universe["segment"] == "fx", "instrument_id"])
    fx = fx[fx["instrument_id"].isin(main)]
    return {
        "equity": by_id(equity, "tr"),
        "crypto": by_id(load_crypto_prices(storage, years), "close"),
        "fx": by_id(fx, "close"),
    }


def run(storage: Storage, now: datetime) -> dict[str, object]:
    questions = build(panels_from_storage(storage, now))
    payload = {
        "version": VERSION,
        "generated_at": now.astimezone(UTC).replace(microsecond=0).isoformat(),
        "window": WINDOW,
        "horizons": list(HORIZONS),
        "questions": questions,
    }
    storage.upload(
        DISPLAY_BUCKET,
        OUT_PATH,
        json.dumps(payload, separators=(",", ":")).encode(),
        "application/json",
    )
    counts = pd.Series([q["asset"] for q in questions]).value_counts().to_dict()
    log.info("practice_published", questions=len(questions), **counts)
    return {"questions": len(questions), **counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze kalibrációs edzés kérdésbank")
    parser.add_argument("--local", type=Path)
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
    print(json.dumps(run(storage, datetime.now(UTC)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
