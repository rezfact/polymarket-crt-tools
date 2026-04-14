from __future__ import annotations

import time
import urllib.parse
from typing import Literal

import pandas as pd

from polymarket_htf.config_env import (
    binance_klines_url,
    ensure_certifi_ssl_env,
    http_user_agent,
    tls_verify_requests,
)
from polymarket_htf.http_retry import requests_get_response

ensure_certifi_ssl_env()

Interval = Literal["1m", "3m", "5m", "15m", "30m", "1h", "4h"]

_CHUNK = 1000  # Binance max per request

_INTERVAL_MS: dict[Interval, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
}


def interval_duration_seconds(interval: str) -> int:
    """Bar length in seconds for a kline interval label (e.g. ``15m`` → 900)."""
    if interval not in _INTERVAL_MS:
        raise ValueError(f"unsupported interval {interval!r}")
    return _INTERVAL_MS[interval] // 1000  # type: ignore[arg-type]


def _klines_to_df(raw: list) -> pd.DataFrame:
    idx = pd.to_datetime([int(r[0]) for r in raw], unit="ms", utc=True)
    return pd.DataFrame(
        {
            "open": [float(r[1]) for r in raw],
            "high": [float(r[2]) for r in raw],
            "low": [float(r[3]) for r in raw],
            "close": [float(r[4]) for r in raw],
            "volume": [float(r[5]) for r in raw],
        },
        index=idx,
    )


def fetch_binance_klines(symbol: str, interval: Interval, *, limit: int = 500) -> pd.DataFrame:
    q = urllib.parse.urlencode({"symbol": symbol.upper(), "interval": interval, "limit": str(limit)})
    url = f"{binance_klines_url()}?{q}"
    r = requests_get_response(
        url,
        headers={"User-Agent": http_user_agent()},
        timeout=25,
        verify=tls_verify_requests(),
    )
    r.raise_for_status()
    raw = r.json()
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"Binance: empty klines for {symbol} {interval}")
    df = _klines_to_df(raw)
    df.index.name = "timestamp"
    return df


def fetch_binance_klines_range(
    symbol: str,
    interval: Interval,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    limit_per_request: int = _CHUNK,
) -> pd.DataFrame:
    """
    Historical klines between ``start`` and ``end`` (UTC), **end exclusive**,
    via repeated Binance ``startTime`` / ``endTime`` requests (max 1000 rows each).
    """
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    else:
        start_ts = start_ts.tz_convert("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")
    else:
        end_ts = end_ts.tz_convert("UTC")
    if end_ts <= start_ts:
        raise ValueError("end must be after start (end exclusive).")

    step_ms = _INTERVAL_MS[interval]
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    cur = start_ms
    all_raw: list = []
    lim = min(_CHUNK, max(1, int(limit_per_request)))

    while cur < end_ms:
        q = urllib.parse.urlencode(
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": str(cur),
                "endTime": str(end_ms),
                "limit": str(lim),
            }
        )
        url = f"{binance_klines_url()}?{q}"
        r = requests_get_response(
            url,
            headers={"User-Agent": http_user_agent()},
            timeout=30,
            verify=tls_verify_requests(),
        )
        r.raise_for_status()
        raw = r.json()
        if not isinstance(raw, list) or not raw:
            break
        all_raw.extend(raw)
        last_open = int(raw[-1][0])
        nxt = last_open + step_ms
        if nxt <= cur:
            break
        cur = nxt
        if len(raw) < lim:
            break
        time.sleep(0.08)

    if not all_raw:
        raise ValueError(f"Binance: no klines in range for {symbol} {interval}")

    df = _klines_to_df(all_raw)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[(df.index >= start_ts) & (df.index < end_ts)]
    df.index.name = "timestamp"
    return df
