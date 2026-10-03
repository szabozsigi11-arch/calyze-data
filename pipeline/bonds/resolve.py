"""A kötvény-becslések kiértékelése (7. fázis).

Ugyanaz a megvalósítás, mint kriptón (`pipeline.crypto.resolve`), a kötvény
leírásával (`pipeline.assetspec.bonds`): UST-naptár, a „hozam-árból” mért
változás, saját táblák, `scope = bonds`. Tézis kötvényre még nincs.

Futtatás:
    uv run python -m pipeline.bonds.resolve
"""

from __future__ import annotations

import sys

from pipeline.assetspec import bonds
from pipeline.crypto.resolve import main

if __name__ == "__main__":
    sys.exit(main(spec=bonds()))
