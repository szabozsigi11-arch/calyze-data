"""Az opciós láncok lekérése (spec/05 2.1b: nem hivatalos forrás, napi egyszer).

A forrás a yfinance — nem hivatalos, bármikor elromolhat. Ezért:
  - minden papír hibája külön kezelődik: egy rossz papír nem viszi el a többit,
  - a papír sora ilyenkor is elkészül, `fetch_failed` okkal,
  - és a hívó (a napi becslés) az EGÉSZ lekérés elhalását is túléli.
"""

from __future__ import annotations

import time
from datetime import date

import pandas as pd

from pipeline import log as logging_setup
from pipeline.options.implied import Implied, choose_expiry, implied_from_chain

log = logging_setup.get_logger(__name__)

#: Két kérés közti szünet: a forrás ingyenes és nem hivatalos, ne terheljük.
PAUSE = 0.05

COLUMNS = [
    "instrument_id",
    "horizon",
    "implied_status",
    "implied_prob",
    "implied_iv",
    "implied_band_low",
    "implied_band_high",
    "implied_expiry",
]


def _row(instrument: str, horizon: int, result: Implied) -> dict[str, object]:
    return {
        "instrument_id": instrument,
        "horizon": horizon,
        "implied_status": result.status,
        "implied_prob": result.prob_up,
        "implied_iv": result.iv,
        "implied_band_low": result.band_low,
        "implied_band_high": result.band_high,
        "implied_expiry": result.expiry,
    }


def fetch_implied(
    instruments: list[tuple[str, str]],
    spots: dict[str, float],
    session: date,
    targets: dict[int, date],
    rate: float | None,
    ticker_factory=None,  # teszteknél kicserélhető
) -> pd.DataFrame:
    """Papíronként és horizontonként az implikált baseline, vagy az ok, amiért nincs."""
    if ticker_factory is None:
        import yfinance as yf

        ticker_factory = yf.Ticker

    rows: list[dict[str, object]] = []
    for instrument, symbol in instruments:
        spot = spots.get(instrument)
        if rate is None or spot is None or not spot > 0:
            reason = "no_rate" if rate is None else "no_spot"
            rows.extend(_row(instrument, h, Implied(reason)) for h in targets)
            continue
        try:
            ticker = ticker_factory(symbol)
            expiries = [date.fromisoformat(e) for e in (ticker.options or ())]
            chains: dict[date, pd.DataFrame] = {}
            for horizon, target in targets.items():
                expiry = choose_expiry(expiries, target, horizon) if expiries else None
                if not expiries:
                    rows.append(_row(instrument, horizon, Implied("no_chain")))
                    continue
                if expiry is None:
                    rows.append(_row(instrument, horizon, Implied("no_expiry")))
                    continue
                if expiry not in chains:
                    chains[expiry] = ticker.option_chain(expiry.isoformat()).calls
                    time.sleep(PAUSE)
                rows.append(
                    _row(
                        instrument,
                        horizon,
                        implied_from_chain(chains[expiry], spot, session, expiry, rate, horizon),
                    )
                )
        except Exception as error:  # noqa: BLE001 — a forrás bármit dobhat; a papír sora ettől még elkészül
            log.info("implied_fetch_failed", instrument=instrument, error=type(error).__name__)
            done = {r["horizon"] for r in rows if r["instrument_id"] == instrument}
            rows.extend(_row(instrument, h, Implied("fetch_failed")) for h in targets if h not in done)
        time.sleep(PAUSE)
    return pd.DataFrame(rows, columns=COLUMNS)
