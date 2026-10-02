"""A kripto-univerzum kiválasztása (`docs/kripto-univerzum.md`).

Egyszer fut, a tulajdonos gépén vagy kézi Actions-futásban. A jelöltlistát a
dokumentumból olvassa, hogy a kettő ne térhessen el. A nyilvános repóba csak a
döntés kerül (kiválasztva / kimaradt, és miért, a rangsor helye); a Yahoo
forgalmi számai nem, mert azok továbbadása nem megengedett
(`docs/adatlicencek.md` a privát repóban).

Futtatás:
    uv run python -m pipeline.universe.select_crypto
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from pipeline.universe import UNIVERSE_FILE

DOC = Path(__file__).resolve().parents[2] / "docs" / "kripto-univerzum.md"
OUT = Path(__file__).with_name("instruments_crypto.csv")
REPORT = Path(__file__).with_name("crypto_selection.json")

AS_OF = date(2026, 10, 1)
SELECTED_ON = date(2026, 10, 2)
MIN_HISTORY_DAYS = 730
MAX_GAP_DAYS = 3
VOLUME_WINDOW = 60
TOP = 50
ALWAYS = ("Bitcoin", "Ethereum")
FIRST_ID = 621


@dataclass
class Candidate:
    name: str
    symbol: str | None = None
    status: str = "pending"
    rank: int | None = None


def candidates_from_doc(text: str) -> list[str]:
    """A 4. fejezet vesszővel elválasztott nevei, sorrendben."""
    match = re.search(r"## 4\. A jelöltlista\n(.*?)\n## ", text, flags=re.S)
    if match is None:
        raise ValueError("a dokumentumban nincs jelöltlista")
    body = " ".join(match.group(1).split())
    names = [n.strip().rstrip(".") for n in body.split(",")]
    return [n for n in names if n]


def resolve(name: str, search: object) -> str | None:
    """A Yahoo-szimbólum: pontosan `<név> USD` nevű, -USD végű kripto-találat."""
    quotes = search(name)  # type: ignore[operator]
    want = f"{name} USD".casefold()
    hits = [
        q["symbol"]
        for q in quotes
        if q.get("quoteType") == "CRYPTOCURRENCY"
        and str(q.get("symbol", "")).endswith("-USD")
        and str(q.get("shortname", "")).casefold() == want
    ]
    return hits[0] if len(hits) >= 1 else None


def history_ok(closes: pd.Series) -> tuple[bool, str]:
    """Legalább 730 nap, és az utolsó 730 napban nincs 3 napnál hosszabb hiány."""
    days = pd.DatetimeIndex(closes.dropna().index).normalize()
    days = days[days <= pd.Timestamp(AS_OF)]
    if days.empty or (pd.Timestamp(AS_OF) - days.min()).days + 1 < MIN_HISTORY_DAYS:
        return False, "short_history"
    window = days[days > pd.Timestamp(AS_OF) - pd.Timedelta(days=MIN_HISTORY_DAYS)]
    full = pd.date_range(pd.Timestamp(AS_OF) - pd.Timedelta(days=MIN_HISTORY_DAYS - 1), pd.Timestamp(AS_OF))
    missing = full.difference(window)
    if len(missing):
        runs = (pd.Series(missing).diff().dt.days != 1).cumsum()
        if pd.Series(missing).groupby(runs).size().max() > MAX_GAP_DAYS:
            return False, "gaps"
    return True, "ok"


def rank(volumes: dict[str, float], names: dict[str, str]) -> list[str]:
    """Az első 50 szimbólum a medián dollárforgalom szerint; a BTC és az ETH mindenképp."""
    order = sorted(volumes, key=lambda s: (-volumes[s], s))
    top = order[:TOP]
    for must in ALWAYS:
        sym = next((s for s, n in names.items() if n == must), None)
        if sym is not None and sym in volumes and sym not in top:
            top = [s for s in top if names[s] not in ALWAYS][: TOP - len(ALWAYS)] + [
                s for s in order if names[s] in ALWAYS
            ]
            break
    return sorted(top, key=lambda s: (-volumes[s], s))


def display_ticker(symbol: str) -> str:
    """A megjelenített név: `UNI7083-USD` → `UNI-USD`.

    A `-USD` utótag marad, mert a puszta rövidítés ütközne részvény-tickerrel
    (DASH = DoorDash).
    """
    base = symbol.removesuffix("-USD")
    return re.sub(r"\d+$", "", base) + "-USD"


def main() -> int:
    import yfinance as yf

    names = candidates_from_doc(DOC.read_text(encoding="utf-8"))
    cands = [Candidate(n) for n in names]

    def search(q: str) -> list[dict[str, object]]:
        return list(yf.Search(q, max_results=10).quotes)

    for c in cands:
        try:
            c.symbol = resolve(c.name, search)
        except Exception:  # noqa: BLE001 — a kereső hibája a jelöltet zárja ki, nem a futást
            c.symbol = None
        if c.symbol is None:
            c.status = "unresolved"

    resolved = [c for c in cands if c.symbol is not None]
    raw = yf.download(
        tickers=[c.symbol for c in resolved],
        start=(AS_OF - timedelta(days=MIN_HISTORY_DAYS + 400)).isoformat(),
        end=(AS_OF + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    volumes: dict[str, float] = {}
    by_symbol = {c.symbol: c for c in resolved}
    for c in resolved:
        sym = str(c.symbol)
        if sym not in raw.columns.get_level_values(0):
            c.status = "no_data"
            continue
        part = raw[sym]
        ok, reason = history_ok(part["Close"])
        if not ok:
            c.status = reason
            continue
        recent = part["Volume"].dropna()
        recent = recent[recent.index <= pd.Timestamp(AS_OF)].tail(VOLUME_WINDOW)
        volumes[sym] = float(recent.median())
        c.status = "eligible"

    top = rank(volumes, {str(c.symbol): c.name for c in resolved})
    for i, sym in enumerate(top, start=1):
        by_symbol[sym].status = "selected"
        by_symbol[sym].rank = i
    for c in resolved:
        if c.status == "eligible":
            c.status = "below_top_50"

    existing = pd.read_csv(UNIVERSE_FILE, dtype=str, keep_default_na=False)
    used = {int(i[2:]) for i in existing["instrument_id"]}
    if FIRST_ID <= max(used):
        print("Az azonosítók ütköznének a részvényekével.", file=sys.stderr)
        return 1
    rows = [
        {
            "instrument_id": f"CZ{FIRST_ID + i:05d}",
            "ticker": display_ticker(sym),
            "name": by_symbol[sym].name,
            "asset_class": "crypto",
            "sector": "",
            "exchange_calendar": "24/7",
            "valid_from": SELECTED_ON.isoformat(),
            "valid_to": "",
            "segment": "crypto",
            "source_symbol": sym,
        }
        for i, sym in enumerate(top)
    ]
    pd.DataFrame(rows).to_csv(OUT, index=False)
    REPORT.write_text(
        json.dumps(
            {
                "selected_on": SELECTED_ON.isoformat(),
                "as_of": AS_OF.isoformat(),
                "rule": "docs/kripto-univerzum.md",
                "candidates": [asdict(c) for c in cands],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    counts = pd.Series([c.status for c in cands]).value_counts().to_dict()
    print(json.dumps({"candidates": len(cands), **counts}, indent=2))
    # A forgalmi számok csak a helyi kimenetre mennek, a repóba nem.
    for i, sym in enumerate(top, start=1):
        print(
            f"{i:2d}. {display_ticker(sym):12s} {by_symbol[sym].name:40s}",
            f"{volumes[sym] / 1e6:12.1f} M USD/nap",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
