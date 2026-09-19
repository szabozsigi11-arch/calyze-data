"""Vállalati események (spec/05, 2.5): felosztás, osztalék, kivezetés.

- A hozam mindig **teljes hozam** (osztalékkal újrabefektetve): a záróárból
  és az osztaléklistából számoljuk (`total_return_prices`).
- A felhasználó által rögzített árat (tézis, gyors trade) a felosztások
  szorzójával igazítjuk a megjelenítésben; az eredeti érték megmarad.
- A kivezetett papír nem tűnik el: az utolsó kereskedési napja a lezárás
  alapja (survivorship bias elleni védelem).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from pipeline.calendar import sessions_back


def split_factor(actions: pd.DataFrame, instrument_id: str, after: date, until: date) -> float:
    """A felosztások szorzata az (after, until] időszakban.

    Egy 4:1 felosztás után a régi ár negyede felel meg a mostaninak: a
    812-es belépő ár mai megfelelője 812 / 4 = 203.
    """
    rows = actions[
        (actions["instrument_id"] == instrument_id)
        & (actions["split_ratio"] > 0)
        & (actions["date"] > after)
        & (actions["date"] <= until)
    ]
    return float(np.prod(rows["split_ratio"].to_numpy())) if not rows.empty else 1.0


def adjust_user_price(
    price: float, actions: pd.DataFrame, instrument_id: str, entered_on: date, today: date
) -> float:
    return price / split_factor(actions, instrument_id, entered_on, today)


def total_return_prices(prices: pd.DataFrame, actions: pd.DataFrame) -> pd.Series:
    """Teljes hozamú árindex papíronként (az első napon 1,0), a záróárból és az osztalékból.

        TR_t = TR_{t-1} · (close_t + D_t) / close_{t-1}

    ahol D_t az aznapi (ex-dátumú) osztalék. Szándékosan nem a forrás
    `adj_close`-át használjuk: azt a forrás minden új osztaléknál
    visszamenőleg átírja, így a tárolt múlt és a friss napok más alapon
    állnának, és a határon hamis hozam keletkezne. Így osztaléknál semmit
    nem kell visszamenőleg újraírni; felosztásnál a forrás a `close`-t is
    igazítja, ott a papír teljes múltja újratöltődik (ritka).
    """
    # Pozíció szerint dolgozunk: az összefűzött évfájlok sorindexe ismétlődhet.
    work = prices.reset_index(drop=True)
    ordered = work.sort_values(["instrument_id", "date"])
    div = (
        actions[actions["dividend"] > 0].groupby(["instrument_id", "date"])["dividend"].sum()
        if not actions.empty
        else pd.Series(dtype=float)
    )
    keys = pd.MultiIndex.from_frame(ordered[["instrument_id", "date"]])
    d = pd.Series(div.reindex(keys).fillna(0.0).to_numpy(), index=ordered.index)
    prev = ordered.groupby("instrument_id")["close"].shift(1)
    growth = ((ordered["close"] + d) / prev).fillna(1.0)
    tr = growth.groupby(ordered["instrument_id"]).cumprod()
    return pd.Series(tr.reindex(work.index).to_numpy(), index=prices.index)


def log_total_returns(prices: pd.DataFrame, actions: pd.DataFrame) -> pd.Series:
    """Napi log teljes hozam papíronként (a célváltozó és a feature-ök alapja)."""
    work = prices.reset_index(drop=True)
    ordered = work.assign(tr=total_return_prices(work, actions)).sort_values(["instrument_id", "date"])
    r = np.log(ordered["tr"]).groupby(ordered["instrument_id"]).diff()
    return pd.Series(r.reindex(work.index).to_numpy(), index=prices.index)


def detect_delisted(prices: pd.DataFrame, last_session: date, gap_sessions: int = 5) -> dict[str, date]:
    """Azok a papírok, amelyeknek az adata `gap_sessions` sessionnél régebben megszakadt.

    A visszaadott dátum az utolsó kereskedési nap: a becslés és a tézis ezzel
    a nappal zárul, `resolution_type` jelöléssel (M3).
    """
    cutoff = sessions_back(last_session, gap_sessions + 1)[0]
    last = prices.groupby("instrument_id")["date"].max()
    return {str(i): d for i, d in last.items() if d < cutoff}
