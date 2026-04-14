"""
Resilient ``requests.get`` for flaky CDNs / resets (Connection reset by peer, etc.).
"""
from __future__ import annotations

import random
import time

import requests


def requests_get_response(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    verify: bool | str,
    attempts: int = 6,
    base_sleep: float = 0.5,
    max_sleep: float = 32.0,
) -> requests.Response:
    """
    ``GET`` with exponential backoff + jitter. Retries on connection/timeouts and 429 / 5xx.

    Returns a :class:`requests.Response` (caller handles 404 / ``raise_for_status``).
    """
    last: BaseException | None = None
    transient = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ReadTimeout,
        requests.exceptions.ChunkedEncodingError,
    )
    for i in range(max(1, int(attempts))):
        try:
            r = requests.get(url, headers=headers, timeout=timeout, verify=verify)
            if r.status_code in (429, 500, 502, 503, 504):
                r.raise_for_status()
            return r
        except transient as e:
            last = e
        except requests.exceptions.HTTPError as e:
            st = e.response.status_code if e.response is not None else None
            if st in (429, 500, 502, 503, 504):
                last = e
            else:
                raise
        if i >= attempts - 1:
            assert last is not None
            raise last
        sleep_s = min(max_sleep, base_sleep * (2**i) + random.random() * 0.35)
        time.sleep(sleep_s)
    raise RuntimeError("requests_get_response: unreachable")
