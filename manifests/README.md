# Daily forecast manifests

One small file per trading session. Each entry is the fingerprint of that
day's forecast package:

```json
{
  "session": "2026-09-18",
  "made_at": "2026-09-18T22:35:04+00:00",
  "model_family": "lgbm-core",
  "model_version": "v1",
  "horizons": [5, 20, 60],
  "instruments": 620,
  "forecasts": 1860,
  "sha256": "…",
  "bytes": 123456,
  "package": "private storage until the data licence allows publication"
}
```

**Why only a fingerprint.** The forecasts themselves are derived from free
market data whose terms do not allow us to show them to anyone else yet. The
SHA-256 here is committed the same night the forecasts are made, so when the
packages can be published, anyone can download one and recompute the hash: if
it matches, the file is exactly what existed on that date. The commit
timestamp is the part that cannot be faked later.

Nothing in this folder is ever rewritten. A missing day is a missing day.
