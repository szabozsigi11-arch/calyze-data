"""Az eredménynapló teljes változata (spec/03, 3.5; `docs/eredmenynaplo.md`).

Nincs benne új mérés: a lezárt becslések (`outcomes/`) összesítése. A napi
sorokból a felület számolja a hőtérképet ÉS a kumulált görbét is, így a kettő
nem csúszhat el egymástól — és a görbe végpontja ugyanaz a szám, mint a
kumulált verdikt kártyáján.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pyarrow as pa

from pipeline.ingest.partitions import to_parquet

#: Horizontonként ennyi legrosszabb becslés (4. fejezet).
WORST_PER_HORIZON = 200
#: Egy hónap fájlja akkor íródik újra, ha ennyi napon belül került bele lezárás.
REWRITE_DAYS = 7
#: A letölthető fájlok helye a megjelenítési tárolóban.
EXPORT_PREFIX = "record"

EXPORT_COLUMNS = [
    "forecast_id",
    "instrument_id",
    "ticker",
    "session",
    "target_session",
    "horizon",
    "regime",
    "model_family",
    "model_version",
    "withheld",
    "prob_up",
    "baseline_prob",
    "actual_return",
    "hit",
    "baseline_hit",
    "brier",
    "baseline_brier",
    "covered",
    "resolution_type",
]


def _r(value: object, digits: int = 4) -> float | None:
    out = float(value)  # type: ignore[arg-type]
    return None if not np.isfinite(out) else round(out, digits)


def enrich(outcomes: pd.DataFrame, forecasts: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """A lezárt sorok kiegészítve a tickerrel és a visszatartás jelölésével.

    A régi csomagokban még nem volt `withheld` oszlop: ott nem volt
    visszatartás, tehát hamis — nem hiányzó.
    """
    if outcomes.empty:
        return pd.DataFrame(columns=[*EXPORT_COLUMNS, "resolved_at"])
    data = outcomes.copy()
    tickers = (
        universe.set_index("instrument_id")["ticker"] if "ticker" in universe else pd.Series(dtype=object)
    )
    data["ticker"] = data["instrument_id"].map(tickers).fillna(data["instrument_id"])
    if not forecasts.empty and "withheld" in forecasts:
        withheld = forecasts.drop_duplicates("forecast_id").set_index("forecast_id")["withheld"]
        data["withheld"] = data["forecast_id"].map(withheld).fillna(False).astype(bool)
    else:
        data["withheld"] = False
    for column in [*EXPORT_COLUMNS, "resolved_at"]:
        if column not in data:
            data[column] = None
    # A `resolved_at` nem megy a letöltésbe, de a havi újraírás ebből dönt.
    keep = [*EXPORT_COLUMNS, "resolved_at"]
    return data[keep].sort_values(["target_session", "horizon", "instrument_id"]).reset_index(drop=True)


def daily(data: pd.DataFrame) -> dict[str, list[list[object]]]:
    """Horizontonként a lezárási napok: [nap, darab, modell-találat, baseline-találat].

    A 30 alatti napok is benne vannak a darabszámmal: a felület üres cellát
    rajzol, és kimondja, hogy kevés — nem tünteti el a napot.
    """
    out: dict[str, list[list[object]]] = {}
    for horizon, part in data.groupby("horizon", sort=True):
        days = part.groupby("target_session", sort=True).agg(
            n=("hit", "size"), hits=("hit", "sum"), baseline_hits=("baseline_hit", "sum")
        )
        out[str(int(horizon))] = [  # type: ignore[call-overload]
            [str(d), int(r.n), int(r.hits), int(r.baseline_hits)] for d, r in days.iterrows()
        ]
    return out


def worst(data: pd.DataFrame, per_horizon: int = WORST_PER_HORIZON) -> list[dict[str, object]]:
    """A legnagyobb Brier-pontú becslések horizontonként; egyenlőnél az újabb elöl."""
    rows: list[dict[str, object]] = []
    for _, part in data.groupby("horizon", sort=True):
        top = part.sort_values(["brier", "target_session"], ascending=[False, False]).head(per_horizon)
        rows.extend(
            {
                "ticker": str(r.ticker),
                "instrument_id": str(r.instrument_id),
                "session": str(r.session),
                "target_session": str(r.target_session),
                "horizon": int(r.horizon),
                "prob_up": _r(r.prob_up),
                "baseline_prob": _r(r.baseline_prob),
                "actual_return": _r(np.expm1(float(r.actual_return)), 6),
                "brier": _r(r.brier),
                "baseline_brier": _r(r.baseline_brier),
                "withheld": bool(r.withheld),
                "delisted": r.resolution_type == "delisted_or_halted",
            }
            for r in top.itertuples()
        )
    return rows


def _month(value: object) -> str:
    return str(value)[:7]


def exports(
    data: pd.DataFrame, existing: set[str], now: datetime, prefix: str = EXPORT_PREFIX
) -> tuple[list[dict[str, object]], list[tuple[str, bytes, str]]]:
    """A havi CSV és Parquet: a jegyzék mindig teljes, fájl csak ahol kell.

    Újraírás, ha a hónapba az utolsó `REWRITE_DAYS` napban lezárás került,
    vagy ha a fájl még nincs meg. A lezárt sor nem változik, ezért a régi
    hónapot nincs miért naponta újra feltölteni.
    """
    if data.empty:
        return [], []
    months = data["target_session"].map(_month)
    stamp = pd.Timestamp(now)
    stamp = stamp.tz_convert("UTC") if stamp.tzinfo else stamp.tz_localize("UTC")
    cutoff = stamp - timedelta(days=REWRITE_DAYS)
    resolved = pd.to_datetime(data["resolved_at"], utc=True)
    fresh = set(months[resolved >= cutoff])
    index: list[dict[str, object]] = []
    files: list[tuple[str, bytes, str]] = []
    for month, part in data.groupby(months, sort=True):
        csv_path = f"{prefix}/{month}.csv"
        parquet_path = f"{prefix}/{month}.parquet"
        index.append({"month": month, "rows": len(part), "csv": csv_path, "parquet": parquet_path})
        if month in fresh or csv_path not in existing or parquet_path not in existing:
            table = part[EXPORT_COLUMNS].reset_index(drop=True)
            buffer = io.StringIO()
            table.to_csv(buffer, index=False, float_format="%.6g")
            files.append((csv_path, buffer.getvalue().encode("utf-8"), "text/csv; charset=utf-8"))
            arrow = pa.Table.from_pandas(table, preserve_index=False)
            files.append((parquet_path, to_parquet(table, arrow.schema), "application/vnd.apache.parquet"))
    return index, files


def build_record(
    outcomes: pd.DataFrame,
    forecasts: pd.DataFrame,
    universe: pd.DataFrame,
    existing: set[str],
    now: datetime,
    prefix: str = EXPORT_PREFIX,
) -> tuple[dict[str, object], list[tuple[str, bytes, str]]]:
    """A `record.json` és a hozzá tartozó letölthető fájlok.

    A kripto a saját mappájába ír (`record-crypto/`), hogy a havi fájlok ne
    írják felül a részvényekét.
    """
    data = enrich(outcomes, forecasts, universe)
    if data.empty:
        return {"generated_at": now.isoformat(), "resolved": 0, "daily": {}, "worst": [], "months": []}, []
    index, files = exports(data, existing, now, prefix)
    return {
        "generated_at": now.isoformat(),
        "resolved": len(data),
        "first": str(data["target_session"].min()),
        "last": str(data["target_session"].max()),
        "daily": daily(data),
        "worst": worst(data),
        "worst_per_horizon": WORST_PER_HORIZON,
        "months": index,
    }, files
