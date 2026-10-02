"""A hír-aréna mérése (`docs/hir-arena.md`).

Négy jelzésfajta, mindegyik azt állítja, hogy a következő 5 napban nagyobb
lesz a mozgás a jelzés előttinél:

- `instrument_shock`: papír-szintű sokk-jel; baseline az aznapi jelzés
  nélküli papírok aránya (párosítva, napra);
- `market_shock`: piaci sokk-jel a SPY-on; baseline a jel nélküli napok aránya;
- `withheld`: a visszatartás jogos-e (a SPY legalább 1,5-szer mozgékonyabb);
- `calendar` és fajtánként (`calendar:fomc` …): hivatalos esemény másnap.

**Élő:** 2026-09-26-tól, a ténylegesen lenyomatolt jelzésekből (a becslés-
csomag mezőiből). **Backtest:** előtte, az árakból újraszámolva, ugyanazzal a
szabállyal. A kettő külön családként kap BH-korrekciót, és soha nem keveredik.

Futtatás:
    uv run python -m pipeline.newsarena.run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import log as logging_setup
from pipeline.config import HISTORY_START, RAW_BUCKET, load_settings
from pipeline.features.run import MACRO_PATH, _load_prices, _read_table, _write_table
from pipeline.ingest.partitions import ACTIONS_PATH, from_parquet
from pipeline.ingest.storage import LocalStorage, Storage, SupabaseStorage
from pipeline.model.evaluate import Comparison, apply_fdr, compare, observations_needed, verdict
from pipeline.newsarena.signals import AFTER, WITHHOLD_RATIO, calendar_days, instrument_frame, market_frame
from pipeline.universe import active_on, load_universe

log = logging_setup.get_logger(__name__)

#: A napi detektor lenyomatolt jelzései ettől a naptól élnek (3. fázis, H6).
LIVE_FROM = date(2026, 9, 26)
#: A naptár 2026-tól fed le (`naptar.md`).
CALENDAR_FROM = date(2026, 1, 1)
RESULTS_PATH = "arena/news.parquet"
METRIC = "hit_rate"


def _record(meta: dict[str, object], c: Comparison) -> dict[str, object]:
    return {
        **meta,
        "metric": c.metric,
        "value": c.value,
        "baseline_value": c.baseline_value,
        "delta": c.delta,
        "n": c.n,
        "n_eff": c.n_eff,
        "p_value_fdr": c.p_value_fdr,
        "verdict": verdict(c),
        "observations_needed": observations_needed(c),
    }


def _days(values: pd.Series | np.ndarray) -> np.ndarray:
    return pd.to_datetime(pd.Series(values)).astype("int64").to_numpy()


def instrument_comparison(frame: pd.DataFrame) -> Comparison | None:
    """Jelzett papír-napok ↔ ugyanazon a napon a jelzés nélküli papírok aránya."""
    usable = frame[frame["vol_after"].notna() & (frame["sigma_before"] > 0)].copy()
    usable["hit"] = (usable["vol_after"] > usable["sigma_before"]).astype(float)
    base = usable[~usable["flag"]].groupby("date")["hit"].mean()
    flagged = usable[usable["flag"]].copy()
    flagged["base"] = flagged["date"].map(base)
    flagged = flagged[flagged["base"].notna()]
    if flagged.empty:
        return None
    return compare(
        METRIC, flagged["hit"].to_numpy(), flagged["base"].to_numpy(), _days(flagged["date"]), AFTER
    )


def day_comparison(days: pd.DataFrame, flag: pd.Series, ratio: float = 1.0) -> Comparison | None:
    """Jelzett napok a SPY-on ↔ a jelzés nélküli napok aránya ugyanabban az időszakban."""
    usable = days[days["vol_after"].notna() & (days["sigma_before"] > 0)]
    flag = flag.reindex(usable.index).fillna(False).astype(bool)
    hit = (
        (usable["vol_after"] >= ratio * usable["sigma_before"])
        if ratio > 1
        else (usable["vol_after"] > usable["sigma_before"])
    )
    hit = hit.astype(float)
    if not flag.any() or flag.all():
        return None
    base = float(hit[~flag].mean())
    flagged = hit[flag]
    return compare(METRIC, flagged.to_numpy(), np.full(len(flagged), base), _days(flagged.index), AFTER)


def measure_period(
    instruments: pd.DataFrame, market: pd.DataFrame, calendar: dict[date, list[str]], period: str
) -> list[tuple[dict[str, object], Comparison]]:
    out: list[tuple[dict[str, object], Comparison]] = []

    def add(signal: str, c: Comparison | None, first: object, last: object) -> None:
        if c is not None:
            out.append(({"signal": signal, "period": period, "first": str(first), "last": str(last)}, c))

    if not instruments.empty:
        add(
            "instrument_shock",
            instrument_comparison(instruments),
            instruments["date"].min(),
            instruments["date"].max(),
        )
    if not market.empty:
        add(
            "market_shock",
            day_comparison(market, market["market_flag"]),
            market.index.min(),
            market.index.max(),
        )
        add(
            "withheld",
            day_comparison(market, market["withheld"], WITHHOLD_RATIO),
            market.index.min(),
            market.index.max(),
        )
        covered = market[[d >= CALENDAR_FROM for d in market.index]]
        if not covered.empty:
            flag = pd.Series([d in calendar for d in covered.index], index=covered.index)
            add("calendar", day_comparison(covered, flag), covered.index.min(), covered.index.max())
            for kind in ("fomc", "cpi", "nfp", "ecb"):
                kind_flag = pd.Series(
                    [kind in calendar.get(d, []) for d in covered.index], index=covered.index
                )
                add(
                    f"calendar:{kind}",
                    day_comparison(covered, kind_flag),
                    covered.index.min(),
                    covered.index.max(),
                )
    return out


def live_flags(
    storage: Storage, instruments: pd.DataFrame, market: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Az élő időszak jelzései a lenyomatolt csomagokból (nem újraszámolva)."""
    frames = []
    for year in range(LIVE_FROM.year, datetime.now(UTC).year + 1):
        for path in storage.list(RAW_BUCKET, f"forecasts/{year}"):
            blob = storage.download(RAW_BUCKET, path)
            if blob is not None:
                frames.append(from_parquet(blob))
    if not frames:
        return instruments.iloc[0:0], market.iloc[0:0]
    packages = pd.concat(frames, ignore_index=True)
    packages = packages[packages["session"] >= LIVE_FROM]
    if packages.empty or "shock_signals" not in packages:
        return instruments.iloc[0:0], market.iloc[0:0]
    per_instrument = packages.drop_duplicates(["instrument_id", "session"])
    flags = {
        (r.instrument_id, r.session): bool(str(r.shock_signals or "")) for r in per_instrument.itertuples()
    }
    live_i = instruments[instruments["date"] >= LIVE_FROM].copy()
    live_i = live_i[[(i, d) in flags for i, d in zip(live_i["instrument_id"], live_i["date"], strict=True)]]
    live_i["flag"] = [flags[(i, d)] for i, d in zip(live_i["instrument_id"], live_i["date"], strict=True)]

    per_day = packages.drop_duplicates("session").set_index("session")
    live_m = market[[d >= LIVE_FROM and d in per_day.index for d in market.index]].copy()
    live_m["market_flag"] = [bool(str(per_day.loc[d, "shock_market"] or "")) for d in live_m.index]
    live_m["withheld"] = [bool(per_day.loc[d, "withheld"]) for d in live_m.index]
    return live_i, live_m


def measure(
    instruments: pd.DataFrame,
    market: pd.DataFrame,
    calendar: dict[date, list[str]],
    live: tuple[pd.DataFrame, pd.DataFrame],
) -> pd.DataFrame:
    """Backtest (LIVE_FROM előtt) és élő, két külön BH-családban."""
    back_i = instruments[instruments["date"] < LIVE_FROM]
    back_m = market[[d < LIVE_FROM for d in market.index]]
    rows = []
    for period, part in (
        ("backtest", measure_period(back_i, back_m, calendar, "backtest")),
        ("live", measure_period(live[0], live[1], calendar, "live")),
    ):
        apply_fdr([c for _, c in part])
        rows += [{**_record(meta, c), "n_tests": len(part)} for meta, c in part]
        log.info("news_arena_period", period=period, comparisons=len(part))
    return pd.DataFrame(rows)


def run(storage: Storage, now: datetime, dry_run: bool = False) -> dict[str, object]:
    prices = _load_prices(storage, list(range(HISTORY_START.year, now.year + 1)))
    if prices.empty:
        raise RuntimeError("Nincs árfolyam a tárban.")
    universe = active_on(load_universe(), now.astimezone(UTC).date())
    prices = prices[prices["instrument_id"].isin(set(universe["instrument_id"]))].copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    actions = _read_table(storage, ACTIONS_PATH)
    if actions is None:
        actions = pd.DataFrame(columns=["instrument_id", "date", "dividend", "split_ratio"])
    macro = _read_table(storage, MACRO_PATH)
    if macro is not None:
        macro = macro.set_index("date")

    instruments = instrument_frame(prices, actions)
    market = market_frame(instruments, universe, macro)
    calendar = calendar_days(sorted(market.index))
    table = measure(instruments, market, calendar, live_flags(storage, instruments, market))
    summary = {
        "records": len(table),
        "backtest": int((table["period"] == "backtest").sum()) if not table.empty else 0,
        "live": int((table["period"] == "live").sum()) if not table.empty else 0,
    }
    if dry_run:
        log.info("news_arena_dry_run", **summary)
        return {**summary, "status": "dry_run"}
    if not table.empty:
        _write_table(storage, RESULTS_PATH, table)
    log.info("news_arena_done", **summary)
    return {**summary, "status": "saved"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Hír-aréna")
    parser.add_argument("--local", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging_setup.configure()
    storage: Storage
    if args.local is not None:
        storage = LocalStorage(args.local)
    else:
        settings = load_settings()
        storage = SupabaseStorage(settings.supabase_url or "", settings.supabase_secret_key or "")
    json.dump(run(storage, datetime.now(UTC), dry_run=args.dry_run), sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
