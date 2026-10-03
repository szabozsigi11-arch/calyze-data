"""A kötvény megjelenítési fájljai (7. fázis): `bonds/…`, `record-bonds/…`.

Ugyanaz a megvalósítás, mint kriptón (`pipeline.crypto.publish`), a kötvény
leírásával; a papír-nézet a hozamot mutatja %-ban.

Futtatás:
    uv run python -m pipeline.bonds.publish
"""

from __future__ import annotations

import sys

from pipeline.assetspec import bonds
from pipeline.crypto.publish import main

if __name__ == "__main__":
    sys.exit(main(spec=bonds()))
