"""Év szerint bontott Parquet-fájlok a privát tárban (spec/05, 9. fejezet, 3. sor).

A napi futás csak a friss év fájlját tölti le és írja vissza; a régiekhez csak
akkor nyúl, ha egy papírnál vállalati esemény miatt a teljes múltat újra kell
igazítani. Így a tár kimenő forgalma kicsi marad.
"""

from __future__ import annotations

import io
from collections.abc import Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.config import RAW_BUCKET
from pipeline.ingest.schema import PRICE_COLUMNS
from pipeline.ingest.storage import Storage

PRICES_PREFIX = "prices_daily"
ACTIONS_PATH = "corporate_actions.parquet"

PRICE_SCHEMA = pa.schema(
    [
        ("instrument_id", pa.string()),
        ("date", pa.date32()),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("adj_close", pa.float64()),
        ("volume", pa.float64()),
        ("source", pa.string()),
        ("fetched_at", pa.timestamp("us", tz="UTC")),
        ("quality", pa.string()),
    ]
)

ACTION_SCHEMA = pa.schema(
    [
        ("instrument_id", pa.string()),
        ("date", pa.date32()),
        ("dividend", pa.float64()),
        ("split_ratio", pa.float64()),
        ("source", pa.string()),
        ("fetched_at", pa.timestamp("us", tz="UTC")),
    ]
)


def partition_path(year: int) -> str:
    return f"{PRICES_PREFIX}/year={year}.parquet"


def to_parquet(frame: pd.DataFrame, schema: pa.Schema) -> bytes:
    table = pa.Table.from_pandas(frame.loc[:, schema.names], schema=schema, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def from_parquet(data: bytes) -> pd.DataFrame:
    return pq.read_table(io.BytesIO(data)).to_pandas()


def read_partition(storage: Storage, year: int) -> pd.DataFrame:
    data = storage.download(RAW_BUCKET, partition_path(year))
    if data is None:
        return pd.DataFrame(columns=list(PRICE_COLUMNS))
    return from_parquet(data)


def existing_years(storage: Storage) -> list[int]:
    years = []
    for path in storage.list(RAW_BUCKET, PRICES_PREFIX):
        name = path.rsplit("/", 1)[-1]
        if name.startswith("year=") and name.endswith(".parquet"):
            years.append(int(name[5:9]))
    return sorted(years)


def upsert(existing: pd.DataFrame, fresh: pd.DataFrame, replace_ids: Iterable[str] = ()) -> pd.DataFrame:
    """Összefésüli a meglévő és a friss sorokat.

    - `replace_ids`: ezeknek a papíroknak a régi sorai mind kiesnek (teljes
      újraigazítás felosztás vagy osztalék után).
    - a többinél a friss sor felülírja az azonos (instrument_id, date) sort.
    """
    replace = set(replace_ids)
    keep = existing[~existing["instrument_id"].isin(replace)] if replace else existing
    if not fresh.empty and not keep.empty:
        keys = pd.MultiIndex.from_frame(fresh[["instrument_id", "date"]])
        mask = ~pd.MultiIndex.from_frame(keep[["instrument_id", "date"]]).isin(keys)
        keep = keep[mask]
    frames = [f for f in (keep, fresh) if not f.empty]
    if not frames:
        return existing.iloc[0:0]
    merged = pd.concat(frames, ignore_index=True)
    return merged.sort_values(["instrument_id", "date"]).reset_index(drop=True)


def write_partitions(storage: Storage, frame: pd.DataFrame) -> list[int]:
    """Évenként külön fájlba írja a táblát; visszaadja a megírt éveket."""
    years = sorted({d.year for d in frame["date"]})
    for year in years:
        part = frame[[d.year == year for d in frame["date"]]]
        storage.upload(
            RAW_BUCKET, partition_path(year), to_parquet(part, PRICE_SCHEMA), "application/octet-stream"
        )
    return years
