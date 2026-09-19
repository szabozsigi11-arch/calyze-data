"""Beállítások környezeti változókból.

Minden kulcs a GitHub Actions titkai közül jön (spec/13, 5. fejezet); a kód
soha nem tartalmaz kulcsot, és soha nem írja ki.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

#: A privát tároló neve: a nyers árfolyam licenc miatt nem publikus (spec/05, 2.4).
RAW_BUCKET = "market-data-raw"

#: A historikus letöltés kezdete. 2005 előtt az ingyenes források hiányosabbak.
HISTORY_START = date(2005, 1, 3)

#: A napi futás ennyi kereskedési napot tölt le újra: a pótlólagos javításokat
#: (késve érkező volumen, korrigált záróár) is elkapja.
DAILY_WINDOW_SESSIONS = 10


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None
    supabase_secret_key: str | None
    tiingo_api_key: str | None
    twelve_data_api_key: str | None

    @property
    def storage_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_secret_key)


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def load_settings() -> Settings:
    return Settings(
        supabase_url=_env("SUPABASE_URL"),
        supabase_secret_key=_env("SUPABASE_SECRET_KEY"),
        tiingo_api_key=_env("TIINGO_API_KEY"),
        twelve_data_api_key=_env("TWELVE_DATA_API_KEY"),
    )
