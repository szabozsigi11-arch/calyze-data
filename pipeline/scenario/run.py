"""A Forgatókönyv csomagja eszközosztályonként (`docs/forgatokonyv.md`).

A modell backtestje hívja, a pontozott sorokkal és az eszközosztály saját
sokk-jeleivel (ugyanazok, mint a hír-arénáé). A felület egy kis JSON-t kap
(`<eszközosztály>/scenario.json`, a kapu mögött), a mérés a privát tárba is
bekerül.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd

from pipeline import log as logging_setup
from pipeline.features.run import _write_table
from pipeline.ingest.storage import Storage
from pipeline.scenario.calibrate import calibration, calm_windows, instrument_shares, measure

log = logging_setup.get_logger(__name__)

DISPLAY_BUCKET = "display"


def publish_scenario(
    storage: Storage,
    scored: pd.DataFrame,
    flags: pd.DataFrame,
    market: pd.Series,
    *,
    asset: str,
    display_prefix: str,
    model: str,
    now: datetime,
) -> dict[str, object]:
    """A hírmentes ablakok eloszlása, gyakorisága és mért pontossága egy eszközosztályra."""
    needed = [
        "instrument_id",
        "date",
        "horizon",
        "expected_return",
        "scale",
        "y",
        "regime",
        "fold",
        "prob_up__naive",
    ]
    frame = scored[needed].copy()
    frame["calm"] = calm_windows(frame, flags, market)
    records = measure(frame)
    payload = {
        "generated_at": now.astimezone(UTC).replace(microsecond=0).isoformat(),
        "asset": asset,
        "model": model,
        "measured_from": str(min(frame["date"])),
        "measured_to": str(max(frame["date"])),
        "definition": "docs/sokk-detektor.md",
        **calibration(frame),
        "instruments": instrument_shares(frame),
        "record": records,
    }
    path = f"{display_prefix}scenario.json"
    storage.upload(
        DISPLAY_BUCKET,
        path,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode(),
        "application/json",
    )
    if records:
        _write_table(
            storage,
            f"arena/scenario_{asset}.parquet",
            pd.DataFrame(records).assign(scope=f"scenario-{asset}"),
        )
    summary = {
        "asset": asset,
        "rows": len(frame),
        "calm_share": round(float(frame["calm"].mean()), 3) if frame["calm"].notna().any() else None,
        "records": len(records),
    }
    log.info("scenario_published", **summary)
    return summary
