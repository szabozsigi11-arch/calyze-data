"""A deviza megjelenítési fájljai (6. fázis, F4): `fx/…`, `record-fx/…`.

Ugyanaz a megvalósítás, mint kriptón (`pipeline.crypto.publish`), a deviza
leírásával (`pipeline.assetspec.fx`).

Futtatás:
    uv run python -m pipeline.fx.publish
"""

from __future__ import annotations

import sys

from pipeline.assetspec import fx
from pipeline.crypto.publish import main

if __name__ == "__main__":
    sys.exit(main(spec=fx()))
