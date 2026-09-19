"""Kulcsot nem szivárogtató HTTP-hívás.

Néhány szolgáltató (FRED, Twelve Data) az API-kulcsot az URL-ben kéri. A
`requests` kivételszövege tartalmazza a teljes URL-t, és ez a **publikus**
Actions-naplóba kerülne. Ezért minden ilyen hívás ezen a burkolón megy át:
a kivételt elkapjuk, és csak a hiba típusát adjuk tovább, az URL-t soha.
"""

from __future__ import annotations

from typing import Any

import requests


class RequestFailed(RuntimeError):
    """Hálózati vagy protokollhiba — a szövege sosem tartalmaz kulcsot vagy URL-t."""


def get_json(url: str, params: dict[str, Any], timeout: float = 30) -> tuple[int, Any]:
    """GET-kérés JSON válasszal.

    Returns:
        (HTTP-státusz, a válasz JSON-ja vagy None)

    Raises:
        RequestFailed: bármilyen hálózati hiba esetén, kulcs nélküli üzenettel.
    """
    try:
        response = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as error:
        raise RequestFailed(f"{type(error).__name__}") from None
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body
