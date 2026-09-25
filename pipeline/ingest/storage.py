"""Privát tár a nyers árfolyamnak (spec/05, 1. fejezet és 2.4).

A nyers adat licenc miatt nem kerülhet a publikus repóba, ezért egy **privát**
Supabase Storage-tárolóban él, amit csak a pipeline ér el a titkos kulccsal.
Ha a tároló valaha nyilvánosra állna, a futás megáll — inkább ne fusson, mint
hogy kiszolgálja a nyers adatot.

A helyi változat (`LocalStorage`) próbafuttatáshoz és teszthez való.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

import requests

from pipeline.log import get_logger

log = get_logger(__name__)


class StorageError(RuntimeError):
    pass


class Storage(Protocol):
    def ensure_private_bucket(self, bucket: str) -> None: ...
    def download(self, bucket: str, path: str) -> bytes | None: ...
    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None: ...
    def list(self, bucket: str, prefix: str) -> list[str]: ...


class SupabaseStorage:
    """A Supabase Storage REST API-ja, az új `sb_secret_` kulccsal.

    A kulcs az `apikey` és az `Authorization` fejlécbe is kerül; az átjáró a
    `Bearer sb_…` értéket a szerepnek megfelelő belső tokenre cseréli.
    """

    #: Átmeneti szerverhibák, amiket érdemes újrapróbálni. A 4xx nincs köztük:
    #: azon az újrapróbálás nem segít, csak késlelteti a hibát.
    RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
    RETRIES = 4

    def __init__(self, url: str, secret_key: str, timeout: float = 60) -> None:
        self.base = f"{url.rstrip('/')}/storage/v1"
        self.session = requests.Session()
        self.session.headers.update({"apikey": secret_key, "Authorization": f"Bearer {secret_key}"})
        self.timeout = timeout

    def _request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        """Kérés újrapróbálással az átmeneti hibákra.

        Egy négyórás futás nem dőlhet el egyetlen 502-n. A várakozás
        duplázódik (1, 2, 4, 8 mp), hogy egy terhelt kiszolgálót ne
        nyomjunk tovább.
        """
        response = self.session.request(method, url, timeout=self.timeout, **kwargs)  # type: ignore[arg-type]
        for attempt in range(self.RETRIES - 1):
            if response.status_code not in self.RETRY_STATUS:
                return response
            time.sleep(2**attempt)
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)  # type: ignore[arg-type]
        return response

    def _check(self, response: requests.Response, what: str) -> None:
        if response.status_code >= 300:
            # A válasz törzsét nem írjuk ki: nem tudjuk, mit tartalmaz.
            raise StorageError(f"{what}: HTTP {response.status_code}")

    @staticmethod
    def _not_found(response: requests.Response) -> bool:
        if response.status_code == 404:
            return True
        if response.status_code == 400:
            try:
                body = response.json()
            except ValueError:
                return False
            return str(body.get("statusCode")) == "404" or body.get("error") in {
                "not_found",
                "Bucket not found",
            }
        return False

    def ensure_private_bucket(self, bucket: str) -> None:
        r = self.session.get(f"{self.base}/bucket/{bucket}", timeout=self.timeout)
        if self._not_found(r):
            created = self.session.post(
                f"{self.base}/bucket",
                json={"id": bucket, "name": bucket, "public": False},
                timeout=self.timeout,
            )
            self._check(created, "tároló létrehozása")
            log.info("bucket_created", bucket=bucket)
            return
        self._check(r, "tároló lekérése")
        if r.json().get("public") is not False:
            raise StorageError(
                f"A(z) {bucket} tároló NYILVÁNOS. A nyers adat nem lehet publikus — a futás megáll."
            )

    def download(self, bucket: str, path: str) -> bytes | None:
        r = self._request("GET", f"{self.base}/object/{bucket}/{path}")
        if self._not_found(r):
            return None
        self._check(r, f"letöltés ({path})")
        return r.content

    #: A Supabase ingyenes sávján a feltöltés fájlonkénti felső határa.
    MAX_UPLOAD_BYTES = 50 * 1024 * 1024

    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        if len(data) > self.MAX_UPLOAD_BYTES:
            raise StorageError(
                f"feltöltés ({path}): {len(data) / 1048576:.0f} MB, a határ "
                f"{self.MAX_UPLOAD_BYTES // 1048576} MB — bontsd kisebb fájlokra vagy összesíts"
            )
        r = self._request(
            "POST",
            f"{self.base}/object/{bucket}/{path}",
            data=data,
            headers={"Content-Type": content_type, "x-upsert": "true", "cache-control": "no-store"},
            timeout=self.timeout,
        )
        self._check(r, f"feltöltés ({path})")

    def list(self, bucket: str, prefix: str) -> list[str]:
        r = self.session.post(
            f"{self.base}/object/list/{bucket}",
            json={"prefix": prefix, "limit": 1000, "sortBy": {"column": "name", "order": "asc"}},
            timeout=self.timeout,
        )
        self._check(r, f"listázás ({prefix})")
        return [f"{prefix.rstrip('/')}/{item['name']}" for item in r.json() if item.get("id")]


class LocalStorage:
    """Helyi mappa a próbafuttatáshoz. A `data/` a .gitignore-ban van."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure_private_bucket(self, bucket: str) -> None:
        (self.root / bucket).mkdir(parents=True, exist_ok=True)

    def download(self, bucket: str, path: str) -> bytes | None:
        p = self.root / bucket / path
        return p.read_bytes() if p.exists() else None

    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        p = self.root / bucket / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def list(self, bucket: str, prefix: str) -> list[str]:
        base = self.root / bucket / prefix
        if not base.exists():
            return []
        return sorted(f"{prefix.rstrip('/')}/{p.name}" for p in base.iterdir() if p.is_file())
