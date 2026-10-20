"""A részvény- és ETF-univerzum bővítése (`docs/reszveny-bovites.md`).

Egyszer fut. A három Wikipédia-lapot előre letöltött HTML-ként kapja (a lap
változik; a futás a rögzítés napi állapotot olvassa). A nyilvános repóba csak
a döntés kerül (felvéve / kimaradt, és miért); a Yahoo forgalmi számai nem.

Futtatás:
    uv run --with lxml python -m pipeline.universe.expand_equities sp500.html sp400.html sp600.html
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from pipeline.universe import UNIVERSE_FILE

SELECTED_ON = date(2026, 10, 19)
ETF_AS_OF = date(2026, 10, 16)
FIRST_ID = 955
ETF_MIN_SESSIONS = 730
ETF_MIN_VOLUME = 5_000_000.0
VOLUME_WINDOW = 60
REPORT = Path(__file__).with_name("equity_selection_2026-10-19.json")
SEGMENT = {500: "sp500", 400: "midcap", 600: "smallcap"}

#: (ticker, kategória a `sector` oszlopba) — `docs/reszveny-bovites.md`, 2.
ETFS: tuple[tuple[str, str], ...] = (
    ("XLY", "Sector: Consumer Discretionary"),
    ("XLP", "Sector: Consumer Staples"),
    ("XLU", "Sector: Utilities"),
    ("XLB", "Sector: Materials"),
    ("XLRE", "Sector: Real Estate"),
    ("XLC", "Sector: Communication Services"),
    ("SMH", "Industry: Semiconductors"),
    ("XBI", "Industry: Biotechnology"),
    ("KRE", "Industry: Regional banks"),
    ("ITB", "Industry: Homebuilders"),
    ("XOP", "Industry: Oil and gas exploration"),
    ("GDX", "Industry: Gold miners"),
    ("XME", "Industry: Metals and mining"),
    ("XRT", "Industry: Retail"),
    ("IYT", "Industry: Transportation"),
    ("ITA", "Industry: Aerospace and defense"),
    ("IGV", "Industry: Software"),
    ("TAN", "Industry: Solar"),
    ("ICLN", "Industry: Clean energy"),
    ("LIT", "Industry: Lithium and batteries"),
    ("URA", "Industry: Uranium"),
    ("KWEB", "Industry: China internet"),
    ("EWJ", "Country: Japan"),
    ("EWG", "Country: Germany"),
    ("EWU", "Country: United Kingdom"),
    ("EWZ", "Country: Brazil"),
    ("INDA", "Country: India"),
    ("FXI", "Country: China"),
    ("EWT", "Country: Taiwan"),
    ("EWY", "Country: South Korea"),
    ("EWC", "Country: Canada"),
    ("EWA", "Country: Australia"),
    ("EWW", "Country: Mexico"),
    ("EPOL", "Country: Poland"),
    ("EWQ", "Country: France"),
    ("EWL", "Country: Switzerland"),
    ("EWI", "Country: Italy"),
    ("EWP", "Country: Spain"),
    ("EZA", "Country: South Africa"),
    ("TUR", "Country: Turkey"),
    ("EIDO", "Country: Indonesia"),
    ("EWS", "Country: Singapore"),
    ("EWH", "Country: Hong Kong"),
    ("ECH", "Country: Chile"),
    ("ARGT", "Country: Argentina"),
    ("VGK", "Region: Europe"),
    ("SHY", "US short-term Treasuries"),
    ("TIP", "US inflation-protected Treasuries"),
    ("AGG", "US aggregate bonds"),
    ("MUB", "US municipal bonds"),
    ("EMB", "Emerging-market bonds"),
    ("BKLN", "US senior loans"),
    ("UNG", "Natural gas"),
    ("CPER", "Copper"),
    ("DBA", "Agriculture"),
    ("DBC", "Broad commodities"),
    ("PPLT", "Platinum"),
    ("VTV", "Style: US large cap value"),
    ("MTUM", "Factor: Momentum"),
    ("USMV", "Factor: Minimum volatility"),
    ("QUAL", "Factor: Quality"),
    ("RSP", "US large cap equal weight"),
    ("SCHD", "US dividend"),
    ("MDY", "US mid cap"),
)


def constituents(path: Path, index: int) -> pd.DataFrame:
    tables = pd.read_html(path)
    table = next(t for t in tables if "Symbol" in t.columns and "GICS Sector" in t.columns)
    out = pd.DataFrame(
        {
            "ticker": table["Symbol"].astype(str).str.strip(),
            "name": table["Security"].astype(str).str.strip(),
            "sector": table["GICS Sector"].astype(str).str.strip(),
            "cik": table["CIK"].astype("Int64").astype(str) if "CIK" in table else "",
            "index": index,
        }
    )
    return out


def company_key(row: pd.Series) -> str:
    """A cég azonosítása: a CIK, ha van, különben a név osztály-jelölés nélkül."""
    if row["cik"] not in ("", "<NA>", "nan"):
        return f"cik:{row['cik']}"
    return "name:" + re.sub(r"\s*\((class|series) [a-z]\)\s*$", "", row["name"].casefold()).strip()


def class_rank(row: pd.Series) -> tuple[int, str]:
    """Az „A” osztály elöl; jelöletlen név után a többi (a 2026-09-19-i szabály)."""
    name = row["name"].casefold()
    if "(class a)" in name:
        return (0, row["ticker"])
    return (1 if "(class" not in name else 2, row["ticker"])


Report = list[dict[str, str]]


def pick_members(lists: list[pd.DataFrame], existing: pd.DataFrame) -> tuple[pd.DataFrame, Report]:
    have = set(existing["ticker"])
    report: list[dict[str, str]] = []
    allm = pd.concat(lists, ignore_index=True)
    # A nagyobb index számít, ha egy papír két listán van (átsorolás közben).
    allm = allm.sort_values("index", key=lambda s: s.map({500: 0, 400: 1, 600: 2}), kind="stable")
    for t in allm[allm.duplicated("ticker")]["ticker"]:
        report.append({"ticker": t, "status": "listed_twice_kept_larger_index"})
    allm = allm.drop_duplicates("ticker")
    allm["key"] = allm.apply(company_key, axis=1)
    # A meglévő univerzum cégeit is ismerni kell (BF.B mellé ne jöjjön BF.A).
    existing_keys = set(allm[allm["ticker"].isin(have)]["key"])
    chosen = []
    for _, group in allm.groupby("key", sort=False):
        group = group.sort_values(by="ticker")
        if group["key"].iloc[0] in existing_keys:
            for t in group[~group["ticker"].isin(have)]["ticker"]:
                report.append({"ticker": t, "status": "share_class_duplicate_of_existing"})
            continue
        best = sorted(group.to_dict("records"), key=lambda r: class_rank(pd.Series(r)))
        chosen.append(best[0])
        for r in best[1:]:
            report.append({"ticker": r["ticker"], "status": f"share_class_duplicate_of_{best[0]['ticker']}"})
    new = pd.DataFrame(chosen)
    new = new[~new["ticker"].isin(have)]
    order = new["index"].map({500: 0, 400: 1, 600: 2})
    new = new.assign(_o=order).sort_values(["_o", "ticker"]).drop(columns="_o")
    for t in new["ticker"]:
        report.append({"ticker": t, "status": "added"})
    return new, report


def check_etfs(existing: pd.DataFrame) -> tuple[list[tuple[str, str]], list[dict[str, str]]]:
    import yfinance as yf

    have = set(existing["ticker"])
    wanted = [(t, s) for t, s in ETFS if t not in have]
    raw = yf.download(
        tickers=[t for t, _ in wanted],
        start=(ETF_AS_OF - timedelta(days=1400)).isoformat(),
        end=(ETF_AS_OF + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    keep, report = [], []
    for t, s in wanted:
        if t not in raw.columns.get_level_values(0):
            report.append({"ticker": t, "status": "no_data"})
            continue
        part = raw[t].dropna(subset=["Close"])
        part = part[part.index <= pd.Timestamp(ETF_AS_OF)]
        if len(part) < ETF_MIN_SESSIONS:
            report.append({"ticker": t, "status": "short_history"})
            continue
        dollar = (part["Close"] * part["Volume"]).tail(VOLUME_WINDOW).median()
        if not dollar >= ETF_MIN_VOLUME:
            report.append({"ticker": t, "status": "below_min_volume"})
            continue
        keep.append((t, s))
        report.append({"ticker": t, "status": "added"})
    return keep, report


def etf_names(tickers: list[str]) -> dict[str, str]:
    import yfinance as yf

    names = {}
    for t in tickers:
        try:
            names[t] = str(yf.Ticker(t).info.get("longName") or t)
        except Exception:  # noqa: BLE001 — a név hiánya nem állítja meg a futást
            names[t] = t
    return names


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    existing = pd.read_csv(UNIVERSE_FILE, dtype=str, keep_default_na=False)
    lists = [constituents(Path(p), n) for p, n in zip(argv, (500, 400, 600), strict=True)]
    members, report = pick_members(lists, existing)
    etfs, etf_report = check_etfs(existing)
    names = etf_names([t for t, _ in etfs])

    rows = [
        {
            "ticker": r["ticker"],
            "name": r["name"],
            "asset_class": "equity",
            "sector": r["sector"],
            "segment": SEGMENT[int(r["index"])],
        }
        for r in members.to_dict("records")
    ]
    rows += [
        {"ticker": t, "name": names[t], "asset_class": "etf", "sector": s, "segment": "etf"} for t, s in etfs
    ]
    for k, row in enumerate(rows):
        row |= {
            "instrument_id": f"CZ{FIRST_ID + k:05d}",
            "exchange_calendar": "XNYS",
            "valid_from": SELECTED_ON.isoformat(),
            "valid_to": "",
        }
    out = pd.concat([existing, pd.DataFrame(rows)[existing.columns]], ignore_index=True)
    if out["ticker"].duplicated().any() or out["instrument_id"].duplicated().any():
        print("Ütköző ticker vagy azonosító.", file=sys.stderr)
        return 1
    out.to_csv(UNIVERSE_FILE, index=False)
    REPORT.write_text(
        json.dumps(
            {
                "selected_on": SELECTED_ON.isoformat(),
                "rule": "docs/reszveny-bovites.md",
                "constituents_source": "Wikipedia, List of S&P 500/400/600 companies, 2026-10-19 (CC BY-SA)",
                "decisions": report + etf_report,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    counts = pd.Series([d["status"] for d in report + etf_report]).value_counts().to_dict()
    by_segment = pd.DataFrame(rows)["segment"].value_counts().to_dict()
    print(json.dumps({"added_rows": len(rows), "by_segment": by_segment, **counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
