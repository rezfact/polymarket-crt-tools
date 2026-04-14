"""
Gamma API: resolve event by slug, discover ``{asset}-updown-{5m|15m}-{unix}`` windows.

Window ids match Polymarket: **America/New_York**-local bar open as epoch seconds
(same convention as the sibling ``btc5m`` project).
"""
from __future__ import annotations

import time
import urllib.parse
from datetime import datetime
from typing import Any

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

from polymarket_htf.assets import slug_token, supported_assets
from polymarket_htf.config_env import (
    ensure_certifi_ssl_env,
    gamma_event_slug_url,
    http_user_agent,
    tls_verify_requests,
)
from polymarket_htf.http_retry import requests_get_response

ensure_certifi_ssl_env()


def _get_json_or_none(url: str, *, timeout: float = 25.0) -> Any | None:
    r = requests_get_response(
        url,
        headers={"User-Agent": http_user_agent()},
        timeout=timeout,
        verify=tls_verify_requests(),
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def updown_window_candidate_ids(
    *,
    tf_minutes: int,
    now_ts: float | None = None,
    neighbor_windows: int = 4,
) -> list[int]:
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo required (Python 3.9+ with tzdata).")
    if tf_minutes not in (5, 15):
        raise ValueError("tf_minutes must be 5 or 15 (Polymarket up/down grids).")
    now_ts = time.time() if now_ts is None else float(now_ts)
    tz = ZoneInfo("America/New_York")
    dt = datetime.fromtimestamp(now_ts, tz=tz)
    floored_minute = (dt.minute // tf_minutes) * tf_minutes
    floored = dt.replace(minute=floored_minute, second=0, microsecond=0)
    center = int(floored.timestamp())
    step = tf_minutes * 60
    out: list[int] = [center]
    for i in range(1, neighbor_windows + 1):
        out.append(center + step * i)
        out.append(center - step * i)
    return out


def tf_slug_label(tf_minutes: int) -> str:
    if tf_minutes == 5:
        return "5m"
    if tf_minutes == 15:
        return "15m"
    raise ValueError(tf_minutes)


def exec_interval_to_polymarket_tf_minutes(exec_interval: str) -> int | None:
    """Up/down Gamma slugs exist for 5m and 15m only."""
    m = {"5m": 5, "15m": 15}
    return m.get(exec_interval)


def updown_window_open_epoch(*, ts_utc: datetime | pd.Timestamp | str, tf_minutes: int) -> int:
    """
    Unix epoch (seconds) of the **start** of the ``tf_minutes`` bar in **America/New_York**
    that contains ``ts_utc`` (same convention as :func:`updown_window_candidate_ids`).
    """
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo required (Python 3.9+ with tzdata).")
    if tf_minutes not in (5, 15):
        raise ValueError("tf_minutes must be 5 or 15")
    t = pd.Timestamp(ts_utc)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    tz = ZoneInfo("America/New_York")
    dt = t.to_pydatetime().astimezone(tz)
    floored_minute = (dt.minute // tf_minutes) * tf_minutes
    floored = dt.replace(minute=floored_minute, second=0, microsecond=0)
    return int(floored.timestamp())


def next_monitor_window_open_epoch(
    *,
    bar_open_utc: datetime | pd.Timestamp | str,
    tf_minutes: int,
    slug_offset_steps: int = 1,
) -> int:
    """
    C3-style: first NY ``tf_minutes`` slot start at/after **exec bar close**, then advance by
    ``slug_offset_steps`` whole windows (default ``1`` = **next** event after the signal bar ends).
    """
    if slug_offset_steps < 0:
        raise ValueError("slug_offset_steps must be >= 0")
    t = pd.Timestamp(bar_open_utc)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    sec = int(tf_minutes) * 60
    bar_close = t + pd.Timedelta(seconds=sec)
    wo = updown_window_open_epoch(ts_utc=bar_close, tf_minutes=tf_minutes)
    return wo + int(slug_offset_steps) * sec


def build_updown_slug(asset: str, *, tf_minutes: int, window_open_ts: int) -> str:
    tok = slug_token(asset)
    lab = tf_slug_label(tf_minutes)
    return f"{tok}-updown-{lab}-{int(window_open_ts)}"


def fetch_event_by_slug(slug: str, *, timeout: float = 25.0) -> dict[str, Any] | None:
    base = gamma_event_slug_url()
    url = f"{base}/{urllib.parse.quote(slug)}"
    data = _get_json_or_none(url, timeout=timeout)
    return data if isinstance(data, dict) else None


def discover_updown_slug(
    asset: str,
    *,
    tf_minutes: int = 15,
    now_ts: float | None = None,
    require_active: bool = True,
    neighbor_windows: int = 4,
) -> str | None:
    for tid in updown_window_candidate_ids(
        tf_minutes=tf_minutes,
        now_ts=now_ts,
        neighbor_windows=neighbor_windows,
    ):
        slug = build_updown_slug(asset, tf_minutes=tf_minutes, window_open_ts=tid)
        ev = fetch_event_by_slug(slug)
        if not ev or not (ev.get("markets") or []):
            continue
        if require_active and (not ev.get("active") or ev.get("closed")):
            continue
        return slug
    return None


def scan_all_assets(
    *,
    tf_minutes: int = 15,
    now_ts: float | None = None,
    require_active: bool = True,
    neighbor_windows: int = 4,
) -> dict[str, str | None]:
    """Return ``{asset: slug_or_none}`` for btc, eth, sol."""
    out: dict[str, str | None] = {}
    for a in supported_assets():
        out[a] = discover_updown_slug(
            a,
            tf_minutes=tf_minutes,
            now_ts=now_ts,
            require_active=require_active,
            neighbor_windows=neighbor_windows,
        )
    return out


def gamma_yes_no_mids(ev: dict[str, Any]) -> tuple[float, float] | None:
    """
    Parse **Up / Down** mid prices from the first Gamma market (``outcomePrices``).

    Returns ``(yes_or_up, no_or_down)`` or ``None`` if missing / not parseable.
    """
    import json

    mks = ev.get("markets") or []
    if not mks or not isinstance(mks, list):
        return None
    m0 = mks[0] if isinstance(mks[0], dict) else {}
    prices = m0.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except json.JSONDecodeError:
            return None
    if not isinstance(prices, list) or len(prices) < 2:
        return None
    try:
        a = float(prices[0])
        b = float(prices[1])
    except (TypeError, ValueError):
        return None
    return a, b


def gamma_entry_price_for_crt_side(ev: dict[str, Any], side: str) -> float | None:
    """Price per share to buy **Up** (CRT ``UP``) or **Down** (CRT ``DOWN``)."""
    pr = gamma_yes_no_mids(ev)
    if pr is None:
        return None
    yes_mid, no_mid = pr
    if side == "UP":
        return yes_mid
    if side == "DOWN":
        return no_mid
    return None


def gamma_side_price_gate(
    ev: dict[str, Any],
    *,
    side: str,
    min_side_price: float | None,
    max_side_price: float | None,
) -> tuple[bool, dict[str, Any]]:
    """
    When ``min_side_price`` / ``max_side_price`` are set, require parsed entry mid in ``[min, max]``.

    Returns ``(ok, detail)``. If bounds are both ``None``, always ``ok=True``.
    If prices cannot be parsed, returns ``ok=False`` with ``detail["parse_ok"]=False``.
    """
    detail: dict[str, Any] = {"parse_ok": False, "side": side, "price": None, "min": min_side_price, "max": max_side_price}
    if min_side_price is None and max_side_price is None:
        detail["parse_ok"] = True
        return True, detail
    p = gamma_entry_price_for_crt_side(ev, side)
    if p is None:
        return False, detail
    detail["parse_ok"] = True
    detail["price"] = p
    if min_side_price is not None and p < float(min_side_price):
        return False, detail
    if max_side_price is not None and p > float(max_side_price):
        return False, detail
    return True, detail


def gamma_outcome_sum_deviation(ev: dict[str, Any]) -> float | None:
    """
    ``abs(p0 + p1 - 1)`` from Gamma ``outcomePrices`` (E3 liquidity / sanity proxy).

    Returns ``None`` if prices are missing or not parseable.
    """
    pr = gamma_yes_no_mids(ev)
    if pr is None:
        return None
    a, b = pr
    return abs(a + b - 1.0)


def gamma_clob_token_ids_up_down(ev: dict[str, Any]) -> tuple[str, str] | None:
    """
    First market on a Gamma **event** (slug): CLOB token ids for **Up** then **Down**.

    ``clobTokenIds`` is usually a JSON string ``["<id_up>", "<id_down>"]``.
    """
    import json

    mks = ev.get("markets") or []
    if not mks or not isinstance(mks, list):
        return None
    m0 = mks[0] if isinstance(mks[0], dict) else {}
    raw = m0.get("clobTokenIds")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            arr = json.loads(raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw, list):
        arr = raw
    else:
        return None
    if len(arr) < 2:
        return None
    return str(arr[0]).strip(), str(arr[1]).strip()


def gamma_market_headline(ev: dict[str, Any]) -> dict[str, Any]:
    """First market block summary for logging."""
    mks = ev.get("markets") or []
    if not mks or not isinstance(mks, list):
        return {}
    m0 = mks[0] if isinstance(mks[0], dict) else {}
    return {
        "question": m0.get("question"),
        "outcomes": m0.get("outcomePrices") or m0.get("outcomes"),
        "volume": m0.get("volume"),
        "active": ev.get("active"),
        "closed": ev.get("closed"),
    }
