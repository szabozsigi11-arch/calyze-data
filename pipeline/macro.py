"""Makro- és piaci kontextus a FRED-ről (spec/05, 2.2; spec/06, 4.).

Két szabály zárja ki a jövőbeli információt:
1. **Egy session késleltetés.** A t napi érték csak a t+1 session feature-jébe
   kerül: a FRED a napi sorokat jellemzően másnap teszi közzé, és a becslés a
   t napi zárás után készül. A backtest és az élő futás így ugyanazt látja.
2. **Csak előre töltés, legfeljebb 5 sessionig.** Visszafelé töltés nincs —
   az a múltba vinné a jövőt (a Kalibrában erre külön teszt volt).

A FRED kötelező közlése a módszertani oldalon: „This product uses the FRED®
API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.”
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import requests

from pipeline.calendar import sessions

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

#: FRED-sorozat → feature-név. A VIXCLS a Cboe tulajdona: csak belső használatra.
SERIES: dict[str, str] = {
    "VIXCLS": "vix",
    "DGS10": "yield_10y",
    "DGS2": "yield_2y",
    "DGS3MO": "yield_3m",
    "DTWEXBGS": "dollar_index",
}

FFILL_LIMIT = 5


class MacroError(RuntimeError):
    pass


def fetch_series(series_id: str, api_key: str, start: date, end: date) -> pd.Series:
    response = requests.get(
        FRED_URL,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        },
        timeout=30,
    )
    if response.status_code != 200:
        # A kulcs az URL-ben van, ezért a választ és az URL-t sem írjuk ki.
        raise MacroError(f"FRED {series_id}: HTTP {response.status_code}")
    obs = response.json().get("observations", [])
    values = pd.to_numeric(pd.Series([o["value"] for o in obs]), errors="coerce")  # a hiány „.”
    index = pd.to_datetime(pd.Series([o["date"] for o in obs])).dt.date
    return pd.Series(values.to_numpy(), index=index.to_numpy(), name=series_id).dropna()


def fetch_all(api_key: str, start: date, end: date) -> pd.DataFrame:
    frame = pd.DataFrame({name: fetch_series(sid, api_key, start, end) for sid, name in SERIES.items()})
    frame.index.name = "date"
    return frame.sort_index()


def align_to_sessions(raw: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """A makrosorokat a tőzsdei napokra igazítja, egy session késleltetéssel.

    Az eredmény t napi sora azt tartalmazza, amit a t-1 napi zárás után már
    tudni lehetett.
    """
    days = sessions(start, end)
    on_sessions = raw.reindex(sorted(set(raw.index) | set(days))).ffill(limit=FFILL_LIMIT).reindex(days)
    lagged = on_sessions.shift(1)
    lagged.index.name = "date"
    lagged["yield_curve_10y2y"] = lagged["yield_10y"] - lagged["yield_2y"]
    return lagged
