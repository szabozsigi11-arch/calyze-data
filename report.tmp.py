from datetime import UTC, datetime
from pathlib import Path
import json
import pandas as pd
from pipeline.config import HISTORY_START
from pipeline.features.run import _load_prices
from pipeline.ingest.storage import LocalStorage
from pipeline.patterns.run import build, display_payload
from pipeline.universe import active_on, load_universe

storage = LocalStorage(Path("data"))
prices = _load_prices(storage, list(range(HISTORY_START.year, 2027)))
universe = active_on(load_universe(), datetime.now(UTC).date())
prices = prices[prices["instrument_id"].isin(set(universe["instrument_id"]))].copy()
prices["date"] = pd.to_datetime(prices["date"]).dt.date
signals, results = build(prices, workers=1)
payload = display_payload(results, signals, datetime.now(UTC))
Path("patterns-local.json").write_text(json.dumps(payload))
print("kész", len(signals), len(results))
