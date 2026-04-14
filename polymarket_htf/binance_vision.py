"""
Load **spot** OHLCV from [Binance Vision](https://data.binance.vision/) monthly zip dumps.

This is an alternative when ``api.binance.com`` REST is blocked or rate-limited.

**Not** the same dataset as futures UM monthly klines
(``data/futures/um/monthly/klines/`` on Vision — different contract prices).
For parity with this repo’s ``BTCUSDT`` spot symbol, use **spot** paths::

  data/spot/monthly/klines/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-YYYY-MM.zip

Reference (futures prefix you mentioned):
https://data.binance.vision/?prefix=data/futures/um/monthly/klines/
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from polymarket_htf.config_env import ensure_certifi_ssl_env, http_user_agent, tls_verify_requests
from polymarket_htf.data import Interval

VISION_ORIGIN_DEFAULT = "https://data.binance.vision"

ensure_certifi_ssl_env()


def spot_monthly_klines_zip_url(
    symbol: str,
    interval: Interval,
    year_month: str,
    *,
    origin: str | None = None,
) -> str:
    """``year_month`` = ``YYYY-MM`` (UTC month file on Vision)."""
    sym = symbol.upper()
    base = (origin or VISION_ORIGIN_DEFAULT).rstrip("/")
    return f"{base}/data/spot/monthly/klines/{sym}/{interval}/{sym}-{interval}-{year_month}.zip"


def _to_utc(ts: pd.Timestamp) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.tz_localize("UTC")
    return t.tz_convert("UTC")


def _month_starts_touching_range(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    """UTC month starts from ``start``'s month through the month containing ``end - 1ns``."""
    s = _to_utc(start)
    e = _to_utc(end)
    if e <= s:
        return []
    first = pd.Timestamp(year=s.year, month=s.month, day=1, tz="UTC")
    last_instant = e - pd.Timedelta(seconds=1)
    last_month = pd.Timestamp(year=last_instant.year, month=last_instant.month, day=1, tz="UTC")
    dr = pd.date_range(first, last_month, freq="MS", tz="UTC")
    return list(dr)


def _read_klines_csv(body: bytes) -> pd.DataFrame:
    """Binance kline CSV: open_time, open, high, low, close, volume, ..."""
    raw = pd.read_csv(io.BytesIO(body), header=None)
    df = raw.iloc[:, :6].copy()
    df.columns = ["open_time", "open", "high", "low", "close", "volume"]
    ot = df["open_time"].to_numpy(dtype="int64", copy=False)
    # Vision monthly zips use **microseconds**; REST klines use **milliseconds**.
    if np.nanmax(ot) > 10**15:
        idx = pd.to_datetime(ot, unit="us", utc=True)
    else:
        idx = pd.to_datetime(ot, unit="ms", utc=True)
    # Use .values so rows align by position (avoid RangeIndex vs DatetimeIndex label join).
    out = pd.DataFrame(
        {
            "open": df["open"].astype(float).to_numpy(),
            "high": df["high"].astype(float).to_numpy(),
            "low": df["low"].astype(float).to_numpy(),
            "close": df["close"].astype(float).to_numpy(),
            "volume": df["volume"].astype(float).to_numpy(),
        },
        index=idx,
    )
    out.index.name = "timestamp"
    return out


def read_spot_klines_zip(path: Path) -> pd.DataFrame:
    """Read one Vision ``*.zip`` (single CSV inside)."""
    with zipfile.ZipFile(path, "r") as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not names:
            raise ValueError(f"No CSV in zip: {path}")
        with zf.open(names[0]) as f:
            raw = f.read()
    return _read_klines_csv(raw)


def download_spot_monthly_zip(
    symbol: str,
    interval: Interval,
    year_month: str,
    dest_dir: Path,
    *,
    vision_origin: str | None = None,
    timeout: float = 120.0,
    skip_missing: bool = False,
) -> Path | None:
    """Download monthly zip if missing. Returns local path, or ``None`` if 404 and ``skip_missing``."""
    from polymarket_htf.http_retry import requests_get_response

    url = spot_monthly_klines_zip_url(symbol, interval, year_month, origin=vision_origin)
    sym = symbol.upper()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{sym}-{interval}-{year_month}.zip"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    r = requests_get_response(
        url,
        headers={"User-Agent": http_user_agent()},
        timeout=timeout,
        verify=tls_verify_requests(),
    )
    if r.status_code == 404:
        if skip_missing:
            return None
        raise FileNotFoundError(f"Vision has no file (404): {url}")
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def load_spot_klines_range_from_vision(
    symbol: str,
    interval: Interval,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    cache_dir: Path = Path("data/binance_vision"),
    vision_origin: str | None = None,
    skip_missing_months: bool = True,
) -> pd.DataFrame:
    """
    Concatenate monthly Vision zips covering ``[start, end)`` (UTC), sorted and deduped.

    If a month file returns **404** (not published yet on Vision), it is skipped when
    ``skip_missing_months`` is true — ranges crossing that month may be **incomplete**.
    """
    import warnings

    months = _month_starts_touching_range(start, end)
    if not months:
        raise ValueError(f"no Vision months in [{start}, {end}); check range and timezone")
    frames: list[pd.DataFrame] = []
    skipped: list[str] = []
    for m in months:
        ym = f"{m.year}-{m.month:02d}"
        dest_dir = cache_dir / symbol.upper() / interval
        zp = download_spot_monthly_zip(
            symbol,
            interval,
            ym,
            dest_dir,
            vision_origin=vision_origin,
            skip_missing=skip_missing_months,
        )
        if zp is None:
            skipped.append(ym)
            continue
        frames.append(read_spot_klines_zip(zp))
    if skipped:
        warnings.warn(f"Binance Vision: missing monthly zip(s), skipped: {skipped}", stacklevel=2)
    if not frames:
        raise ValueError(f"No Vision data could be loaded for {symbol} {interval} (all months missing?)")
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    s = _to_utc(start)
    e = _to_utc(end)
    df = df[(df.index >= s) & (df.index < e)]
    if df.empty:
        raise ValueError(f"No rows after slice [{start}, {end}) for {symbol} {interval}")
    return df
