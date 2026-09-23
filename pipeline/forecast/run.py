"""Napi becslés: a megjelenítés ELŐTT lementve (spec/06, 1. lépés).

A termék egyetlen visszamenőleg nem hamisítható állítása az idő. Ezért:

- a napi becslés-csomag a privát tárba kerül, és **soha nem íródik felül**: ha
  az adott sessionre már van csomag, a futás nem ír, hanem kilép;
- a csomag SHA-256 lenyomata egy kis manifestben a **publikus repóba**
  commitolódik. A commit időbélyege bizonyítja, hogy a becslés akkor már
  megvolt, és bárki újraszámolhatja a hash-t, amikor a csomag nyilvánossá
  válik (az adatlicenc rendezése után; lásd `docs/adatlicencek.md` a másik
  repóban);
- a becslés azonosítója determinisztikus (`uuid5`), így ugyanarra a napra és
  papírra kétszer nem keletkezhet két különböző azonosítójú sor.

Futtatás:
    uv run python -m pipeline.forecast.run
    uv run python -m pipeline.forecast.run --local data --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import log as logging_setup
from pipeline.calendar import last_closed_session, session_lag, sessions_back
from pipeline.config import RAW_BUCKET, load_settings
from pipeline.features.run import (
    MACRO_PATH,
    REGIME_PATH,
    _load_prices,
    _read_table,
    build_features,
)
from pipeline.ingest.partitions import ACTIONS_PATH
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.model.baselines import add_sector_return
from pipeline.model.config import HORIZONS, MIN_HISTORY_SESSIONS, MODEL_FAMILY, MODEL_VERSION
from pipeline.model.run import MODEL_PREFIX
from pipeline.universe import active_on, load_universe

log = logging_setup.get_logger(__name__)

FORECAST_PREFIX = "forecasts"
#: A becslés-azonosítók névtere (rögzített, hogy az azonosító reprodukálható legyen).
NAMESPACE = uuid.UUID("4d1f0d9e-2a3b-5c6d-8e7f-000000000001")
#: Ennyi év árfolyamát tölti le a napi futás (az EMA-200 és a 252 napos momentum miatt).
LOOKBACK_YEARS = 3

# Ennyi kihagyott kereskedési napig még becslünk a legfrissebb meglévő adatból.
# Fölötte a forrás nem „késik", hanem kiesett: olyankor a hallgatás az őszinte
# válasz, nem egy elavult adatra épített szám.
MAX_SOURCE_LAG_SESSIONS = 3


def forecast_id(instrument_id: str, session: date, horizon: int, version: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{instrument_id}|{session.isoformat()}|{horizon}|{version}"))


def target_session(session: date, horizon: int, sessions: list[date]) -> date | None:
    """A horizont vége: az N-edik session zárása a becslés napja után."""
    try:
        i = sessions.index(session)
    except ValueError:
        return None
    return sessions[i + horizon] if i + horizon < len(sessions) else None


def package_path(session: date) -> str:
    return f"{FORECAST_PREFIX}/{session.year}/{session.isoformat()}.parquet"


def build_forecasts(
    features: pd.DataFrame,
    prices: pd.DataFrame,
    session: date,
    models: dict[int, object],
    future_sessions: list[date],
    made_at: datetime,
) -> pd.DataFrame:
    """A session napi becslések minden lefedett papírra, horizontonként."""
    today = features[features["date"] == session]
    today = today[today["history_sessions"] >= MIN_HISTORY_SESSIONS]
    if today.empty:
        raise RuntimeError(f"Nincs feature-sor a(z) {session} sessionre.")

    last_close = (
        prices[prices["date"] == session].set_index("instrument_id")["close"].astype("float64").to_dict()
    )
    rows: list[pd.DataFrame] = []
    for horizon in HORIZONS:
        bundle = models[horizon]
        model = bundle["model"]  # type: ignore[index]
        naive = bundle["baselines"]["naive"]  # type: ignore[index]
        out = model.predict(today)
        # A magyarázat a csomag része, tehát a napi lenyomat fedi: utólag nem
        # gyártható le másként, mint ahogy a becslés készült.
        out["contributions"] = [json.dumps(c, separators=(",", ":")) for c in model.contributions(today)]
        # A horizontot itt állítjuk be, nem a modelltől vesszük: a csomag
        # szerkezete akkor is helyes marad, ha egy modell rosszul tölti ki.
        out["horizon"] = horizon
        base = naive.predict(today)
        out["baseline_prob"] = base["prob_up"].to_numpy()
        out["baseline_id"] = "naive"
        out["session"] = session
        out["target_session"] = target_session(session, horizon, future_sessions)
        out["made_at"] = pd.Timestamp(made_at)
        out["model_family"] = MODEL_FAMILY
        out["model_version"] = MODEL_VERSION
        out["regime"] = today["regime"].to_numpy()
        # A sáv árban is: a záróárra vetítve (a log teljes hozam sávjából).
        close = np.array([last_close.get(i, np.nan) for i in out["instrument_id"]])
        out["close"] = close
        out["price_low"] = close * np.exp(out["band_low"].to_numpy())
        out["price_high"] = close * np.exp(out["band_high"].to_numpy())
        out["expected_price"] = close * np.exp(out["expected_return"].to_numpy())
        out["forecast_id"] = [forecast_id(i, session, horizon, MODEL_VERSION) for i in out["instrument_id"]]
        rows.append(out)

    frame = pd.concat(rows, ignore_index=True)
    return frame.drop(columns=["prob_up_raw"], errors="ignore")


def load_models(storage: Storage) -> dict[int, object]:
    models: dict[int, object] = {}
    for horizon in HORIZONS:
        blob = storage.download(RAW_BUCKET, f"{MODEL_PREFIX}/h{horizon}.pkl")
        if blob is None:
            raise RuntimeError(
                f"Nincs betanított modell a(z) {horizon} napos horizontra "
                "— előbb: python -m pipeline.model.run --task train"
            )
        models[horizon] = pickle.loads(blob)  # noqa: S301 — saját, privát tárból származó fájl
    return models


def manifest_entry(
    session: date, package: bytes, frame: pd.DataFrame, made_at: datetime
) -> dict[str, object]:
    """A publikus repóba kerülő kis manifest: lenyomat, méret, darabszámok."""
    return {
        "session": session.isoformat(),
        "made_at": made_at.isoformat(timespec="seconds"),
        "model_family": MODEL_FAMILY,
        "model_version": MODEL_VERSION,
        "horizons": sorted(int(h) for h in frame["horizon"].unique()),
        "instruments": int(frame["instrument_id"].nunique()),
        "forecasts": len(frame),
        "sha256": hashlib.sha256(package).hexdigest(),
        "bytes": len(package),
        "package": "private storage until the data licence allows publication",
    }


def choose_session(available: date, expected: date) -> date:
    """Melyik napra szóljon a becslés: az ADAT napjára, nem a naptáréra.

    A naptár tudja, mikor volt tőzsdenap; az ingyenes forrás viszont néha
    egy-egy napot kihagy, vagy késve teszi közzé. Ha a naptárhoz
    ragaszkodnánk, a futás elszállna, és aznap nem mérnénk semmit — pedig a
    meglévő adatra lehetne becslést adni.

    Amit nem csinálunk: nem találunk ki árat a hiányzó napra, és nem
    tüntetjük fel a becslést frissebbnek, mint az adat, amiből készült.

    `MAX_SOURCE_LAG_SESSIONS` fölött viszont megállunk: annyi kihagyás után a
    forrás nem késik, hanem kiesett, és a hallgatás az őszinte válasz.
    """
    lag = session_lag(available, expected)
    if lag > MAX_SOURCE_LAG_SESSIONS:
        raise RuntimeError(
            f"A forrás {lag} kereskedési nappal marad el: a legfrissebb adat {available}, "
            f"az utolsó zárt nap {expected}. Ennyi kihagyás után nem becslünk."
        )
    if lag > 0:
        log.info("forecast_stale_source", session=str(available), expected=str(expected), lag=lag)
    return available


def run(storage: Storage, now: datetime, dry_run: bool = False) -> dict[str, object]:
    expected = last_closed_session(now)
    if storage.download(RAW_BUCKET, package_path(expected)) is not None:
        log.info("forecast_already_saved", session=str(expected))
        return {"session": str(expected), "status": "already_saved"}

    universe = active_on(load_universe(), now.astimezone(UTC).date())
    years = list(range(expected.year - LOOKBACK_YEARS + 1, expected.year + 1))
    prices = _load_prices(storage, years)
    actions = _read_table(storage, ACTIONS_PATH)
    if actions is None:
        actions = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])
    regime = _read_table(storage, REGIME_PATH)
    macro = _read_table(storage, MACRO_PATH)
    if regime is None:
        raise RuntimeError("Nincs rezsim-tábla — előbb a feature-futás kell.")
    if macro is not None:
        macro = macro.set_index("date")

    features = add_sector_return(build_features(prices, actions, universe, regime, macro))

    session = choose_session(max(features["date"]), expected)

    if storage.download(RAW_BUCKET, package_path(session)) is not None:
        log.info("forecast_already_saved", session=str(session))
        return {"session": str(session), "status": "already_saved"}

    models = load_models(storage)
    # A horizont végéhez a jövőbeli kereskedési napok is kellenek: a naptárból,
    # nem az árfolyamból (az még nem létezik).
    from pipeline.calendar import calendar

    cal = calendar()
    future = [
        ts.date()
        for ts in cal.sessions_in_range(pd.Timestamp(sessions_back(session, 2)[0]), cal.last_session)
    ]
    frame = build_forecasts(features, prices, session, models, future, now.astimezone(UTC))

    package = _package_bytes(frame)
    entry = manifest_entry(session, package, frame, now.astimezone(UTC))
    if dry_run:
        log.info("forecast_dry_run", **entry)
        return {**entry, "status": "dry_run"}

    storage.upload(RAW_BUCKET, package_path(session), package, "application/octet-stream")
    storage.upload(
        RAW_BUCKET,
        f"runs/forecast/{session.isoformat()}.json",
        json.dumps(entry, indent=2).encode(),
        "application/json",
    )
    log.info("forecast_saved", **entry)
    return {**entry, "status": "saved"}


def _package_bytes(frame: pd.DataFrame) -> bytes:
    import io

    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pandas(frame, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calyze napi becslés")
    parser.add_argument("--local", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--manifest-dir", type=Path, help="ide írja a manifestet (a publikus repóban)")
    args = parser.parse_args(argv)

    logging_setup.configure()
    settings = load_settings()
    if args.local:
        storage: Storage = LocalStorage(args.local)
    elif settings.supabase_url and settings.supabase_secret_key:
        storage = SupabaseStorage(settings.supabase_url, settings.supabase_secret_key)
    else:
        log.error("storage_not_configured")
        return 2

    result = run(storage, datetime.now(UTC), dry_run=args.dry_run)
    if args.manifest_dir and result.get("status") == "saved":
        session = date.fromisoformat(str(result["session"]))
        out = args.manifest_dir / str(session.year)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{session.isoformat()}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
