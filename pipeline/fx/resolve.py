"""A deviza-becslések és -tézisek kiértékelése (6. fázis, F4).

Ugyanaz a megvalósítás, mint kriptón (`pipeline.crypto.resolve`), a deviza
leírásával (`pipeline.assetspec.fx`): TARGET-naptár, saját táblák, `scope = fx`.

Futtatás:
    uv run python -m pipeline.fx.resolve
"""

from __future__ import annotations

import sys

from pipeline.assetspec import fx
from pipeline.crypto.resolve import main

if __name__ == "__main__":
    sys.exit(main(spec=fx()))
