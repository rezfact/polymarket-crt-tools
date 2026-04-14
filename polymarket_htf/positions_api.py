"""
Read-only Polymarket **Data API** positions (paginated).

Used by redeem (resolved) and take-profit watcher (open tradeable).
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from web3 import Web3

from polymarket_htf.config_env import ensure_certifi_ssl_env, http_user_agent, tls_verify_requests

ensure_certifi_ssl_env()

DATA_API_POSITIONS = "https://data-api.polymarket.com/positions"


def polymarket_positions_api_ping(user: str, *, limit: int = 5, timeout: float = 25.0) -> tuple[bool, str]:
    """
    Lightweight check that Polymarket **Data API** accepts ``user`` and returns HTTP 200 + JSON list.

    Does **not** prove CLOB order signing or builder keys — only that the profile address is
    queryable on ``/positions`` (same host as portfolio / redeem tooling).
    """
    import requests

    user_c = Web3.to_checksum_address(user)
    lim = max(1, min(50, int(limit)))
    params = {"user": user_c, "sizeThreshold": "0", "limit": str(lim), "offset": "0"}
    url = f"{DATA_API_POSITIONS}?{urllib.parse.urlencode(params)}"
    r = requests.get(
        url,
        headers={"User-Agent": http_user_agent()},
        timeout=float(timeout),
        verify=tls_verify_requests(),
    )
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    chunk = r.json()
    if not isinstance(chunk, list):
        return False, "response is not a JSON list"
    return True, f"ok rows_in_page={len(chunk)}"


def fetch_positions(
    user: str,
    *,
    redeemable: bool | None = None,
    limit_per_page: int = 100,
    max_pages: int = 50,
) -> list[dict[str, Any]]:
    """
    Return position dicts with ``size > 0``.

    If ``redeemable`` is set, pass ``redeemable=true|false`` (API-dependent).
    """
    import requests

    user_c = Web3.to_checksum_address(user)
    out: list[dict[str, Any]] = []
    offset = 0
    lim = min(500, max(1, limit_per_page))
    for _ in range(max_pages):
        params: dict[str, str] = {
            "user": user_c,
            "sizeThreshold": "0",
            "limit": str(lim),
            "offset": str(offset),
        }
        if redeemable is not None:
            params["redeemable"] = "true" if redeemable else "false"
        url = f"{DATA_API_POSITIONS}?{urllib.parse.urlencode(params)}"
        r = requests.get(
            url,
            headers={"User-Agent": http_user_agent()},
            timeout=30,
            verify=tls_verify_requests(),
        )
        r.raise_for_status()
        chunk = r.json()
        if not isinstance(chunk, list) or not chunk:
            break
        for p in chunk:
            if isinstance(p, dict):
                try:
                    sz = float(p.get("size") or 0)
                except (TypeError, ValueError):
                    sz = 0.0
                if sz > 0:
                    out.append(p)
        if len(chunk) < lim:
            break
        offset += len(chunk)
    return out
