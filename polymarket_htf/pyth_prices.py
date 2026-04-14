"""
Pyth **Benchmarks** TradingView OHLC (HTTP ``history`` UDF-style bars).

Same idea as the sibling ``btc5m`` project: Pyth’s aggregated **Crypto.*/USD** bars are
closer to an **oracle-style** path than exchange tape, but **still not** Polymarket’s
Chainlink settlement stream.

Optional **API key**: set ``PYTH_API_KEY`` (or ``PYTH_BENCHMARKS_API_KEY``) to attach auth
headers for your Pyth / Benchmarks tier (see :func:`polymarket_htf.config_env.pyth_benchmarks_request_headers`).

Docs: https://docs.pyth.network/price-feeds
"""
from __future__ import annotations

import json
import time
import urllib.parse
from typing import Any, Literal

import pandas as pd

from polymarket_htf.config_env import (
    ensure_certifi_ssl_env,
    pyth_benchmarks_request_headers,
    pyth_benchmarks_tv_history_url,
    tls_verify_requests,
)
from polymarket_htf.http_retry import requests_get_response

Interval = Literal["1m", "3m", "5m", "15m", "30m", "1h", "4h"]

INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
}

INTERVAL_TO_TV_MINUTES: dict[str, int] = {
    "1m": 1,
    "3m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 60,
}


ensure_certifi_ssl_env()


def _chunk_seconds_for_interval(interval: str) -> int:
    m = INTERVAL_MINUTES[interval]
    bar_sec = m * 60
    target_bars = 2000
    chunk = target_bars * bar_sec
    return int(min(chunk, 300 * 24 * 3600))


def _seconds_per_interval(interval: str) -> int:
    m = INTERVAL_MINUTES.get(interval)
    if m is None:
        raise ValueError(f"Unsupported interval {interval!r}")
    return m * 60


def _get_json(url: str, *, timeout: float = 45.0) -> Any:
    r = requests_get_response(
        url,
        headers=pyth_benchmarks_request_headers(),
        timeout=timeout,
        verify=tls_verify_requests(),
        attempts=10,
        max_sleep=48.0,
    )
    r.raise_for_status()
    return r.json()


def tv_history_raw(
    symbol: str,
    *,
    resolution_minutes: int,
    from_ts: int,
    to_ts: int,
    timeout: float = 45.0,
) -> dict[str, Any]:
    q = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "resolution": str(resolution_minutes),
            "from": str(int(from_ts)),
            "to": str(int(to_ts)),
        }
    )
    url = f"{pyth_benchmarks_tv_history_url()}?{q}"
    data = _get_json(url, timeout=timeout)
    if not isinstance(data, dict):
        raise ValueError(f"Pyth TV: expected JSON object, got {type(data)}")
    return data


def tv_response_to_ohlcv(data: dict[str, Any]) -> pd.DataFrame:
    status = data.get("s")
    if status == "no_data":
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    if status != "ok":
        err = data.get("errmsg", data)
        raise ValueError(f"Pyth TV history error: {err}")
    t = data.get("t") or []
    if not isinstance(t, list) or not t:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    idx = pd.to_datetime([int(x) for x in t], unit="s", utc=True)
    vols = data.get("v")
    if not isinstance(vols, list) or len(vols) != len(t):
        vols = [0.0] * len(t)
    df = pd.DataFrame(
        {
            "open": [float(x) for x in data["o"]],
            "high": [float(x) for x in data["h"]],
            "low": [float(x) for x in data["l"]],
            "close": [float(x) for x in data["c"]],
            "volume": [float(x) for x in vols],
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return df


def _resample_ohlcv(df: pd.DataFrame, bar_minutes: int) -> pd.DataFrame:
    if df.empty:
        return df
    rule = f"{bar_minutes}min"
    g = df.sort_index().resample(rule, label="left", closed="left")
    out = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
        }
    )
    out = out.dropna(subset=["open", "high", "low", "close"])
    out.index.name = "timestamp"
    return out


def fetch_pyth_klines(
    interval: Interval,
    *,
    symbol: str = "Crypto.BTC/USD",
    limit: int = 500,
    end_ts: int | None = None,
    timeout: float = 45.0,
) -> pd.DataFrame:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if interval == "3m":
        need_1m = max(limit * 3 + 100, limit + 50)
        df1 = fetch_pyth_klines("1m", symbol=symbol, limit=need_1m, end_ts=end_ts, timeout=timeout)
        df = _resample_ohlcv(df1, 3)
        if len(df) > limit:
            df = df.iloc[-limit:]
        return df
    if interval == "4h":
        need_1h = max(limit * 4 + 120, limit + 80)
        df1 = fetch_pyth_klines("1h", symbol=symbol, limit=need_1h, end_ts=end_ts, timeout=timeout)
        df = _resample_ohlcv(df1, 240)
        if len(df) > limit:
            df = df.iloc[-limit:]
        return df

    sec = _seconds_per_interval(interval)
    res_min = INTERVAL_TO_TV_MINUTES[interval]
    to_ts = int(end_ts if end_ts is not None else time.time())
    span = int(sec * limit * 1.15) + sec
    from_ts = max(0, to_ts - span)
    raw = tv_history_raw(symbol, resolution_minutes=res_min, from_ts=from_ts, to_ts=to_ts, timeout=timeout)
    df = tv_response_to_ohlcv(raw)
    if df.empty:
        return df
    df = df.sort_index()
    if len(df) > limit:
        df = df.iloc[-limit:]
    return df


def fetch_pyth_klines_range(
    interval: Interval,
    *,
    symbol: str = "Crypto.BTC/USD",
    since: pd.Timestamp,
    until: pd.Timestamp,
    timeout: float = 60.0,
) -> pd.DataFrame:
    since = pd.Timestamp(since).tz_convert("UTC") if since.tzinfo else since.tz_localize("UTC")
    until = pd.Timestamp(until).tz_convert("UTC") if until.tzinfo else until.tz_localize("UTC")
    from_sec = int(since.timestamp())
    to_sec = int(until.timestamp())
    if from_sec >= to_sec:
        raise ValueError("since must be < until")
    if interval == "3m":
        df1 = fetch_pyth_klines_range("1m", symbol=symbol, since=since, until=until, timeout=timeout)
        out = _resample_ohlcv(df1, 3)
        if out.empty:
            return out
        return out.loc[(out.index >= since) & (out.index < until)]
    if interval == "4h":
        df1 = fetch_pyth_klines_range("1h", symbol=symbol, since=since, until=until, timeout=timeout)
        out = _resample_ohlcv(df1, 240)
        if out.empty:
            return out
        return out.loc[(out.index >= since) & (out.index < until)]

    res_min = INTERVAL_TO_TV_MINUTES[interval]
    parts: list[pd.DataFrame] = []
    step = _chunk_seconds_for_interval(interval)
    chunk_start = from_sec
    while chunk_start < to_sec:
        chunk_end = min(chunk_start + step, to_sec)
        raw = tv_history_raw(
            symbol,
            resolution_minutes=res_min,
            from_ts=chunk_start,
            to_ts=chunk_end,
            timeout=timeout,
        )
        part = tv_response_to_ohlcv(raw)
        if not part.empty:
            parts.append(part)
        chunk_start = chunk_end
    if not parts:
        return tv_response_to_ohlcv({"s": "no_data"})
    out = pd.concat(parts).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out = out.loc[(out.index >= since) & (out.index < until)]
    return out
