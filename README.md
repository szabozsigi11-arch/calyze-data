# calyze-data

The public measurement pipeline behind **Calyze**, a research and measurement
tool that does not try to predict prices, but measures how predictable they
are at all. Calyze is not investment advice.

This repository is public on purpose. Every forecast will be saved before
anyone sees it, and a fingerprint (SHA-256) of each day's forecast package
will be committed here. The commit timestamp is the proof that nothing was
rewritten afterwards.

## What is here

| Path | What it does |
|---|---|
| `pipeline/universe/instruments.csv` | The covered instruments. Each has a permanent internal ID (`CZ00001`); tickers are display names and may change. |
| `pipeline/ingest/` | Daily end-of-day prices from free sources (yfinance → Tiingo → Twelve Data), with a fallback chain. |
| `pipeline/calendar.py` | Trading sessions from `exchange_calendars` (XNYS). Horizons count sessions, not calendar days. |
| `tests/` | Calendar and time-zone edge cases, fallback behaviour, storage safety. |

## What is not here

**Raw market data.** The free data sources do not allow redistribution, so
raw prices and features live in private storage. Only Calyze's own output
(forecasts, outcomes, statistics, daily fingerprints) will be published here.

## Status

Phase 0: the daily price download runs on a schedule. Forecasts and their
public fingerprints start in Phase 1.

## Licence

- **Code:** [PolyForm Noncommercial 1.0.0](LICENSE.md). You may read, run and
  use it to verify the published fingerprints, for any noncommercial purpose.
  Commercial use needs written permission.
- **Published data** (daily fingerprints, and later the forecast packages):
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — use it freely,
  name Calyze as the source. This does not cover raw market data, which is
  never published here.
