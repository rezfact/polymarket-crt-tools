"""
Hermes **latest** aggregate prices (confidence + publish time).

Public endpoint (rate-limited): https://docs.pyth.network/price-feeds/api-instances-and-providers/hermes

Set ``PYTH_HERMES_URL`` to your provider if you have a dedicated Pyth / Hermes API.
Feed IDs: https://pyth.network/developers/price-feed-ids (use **64 hex without 0x** in query).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from polymarket_htf.config_env import (
    ensure_certifi_ssl_env,
    http_user_agent,
    pyth_hermes_api_base,
    tls_verify_requests,
)
from polymarket_htf.http_retry import requests_get_response

ensure_certifi_ssl_env()


def decode_scaled_price(price: str | int, expo: int) -> float:
    """Pyth integer ``price`` with exponent ``expo`` (often -8)."""
    return float(int(str(price))) * (10.0**int(expo))


@dataclass
class HermesLatest:
    feed_id: str
    price: float
    conf: float
    publish_time: int


def fetch_latest_price_feeds(feed_ids: list[str], *, timeout: float = 25.0) -> list[HermesLatest]:
    """``feed_ids`` = 64-char hex **without** ``0x`` prefix."""
    base = pyth_hermes_api_base().rstrip("/")
    qs = "&".join(f"ids[]={fid.lower().removeprefix('0x')}" for fid in feed_ids)
    url = f"{base}/api/latest_price_feeds?{qs}"
    r = requests_get_response(
        url,
        headers={"User-Agent": http_user_agent()},
        timeout=timeout,
        verify=tls_verify_requests(),
    )
    r.raise_for_status()
    raw = r.json()
    if not isinstance(raw, list):
        raise ValueError(f"Hermes: expected list, got {type(raw)}")
    out: list[HermesLatest] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        fid = str(row.get("id", ""))
        pobj = row.get("price") or {}
        if not isinstance(pobj, dict):
            continue
        price = decode_scaled_price(pobj["price"], int(pobj["expo"]))
        conf = decode_scaled_price(pobj["conf"], int(pobj["expo"]))
        pt = int(pobj.get("publish_time", 0))
        out.append(HermesLatest(feed_id=fid, price=price, conf=conf, publish_time=pt))
    return out


def default_feed_id_for_asset(asset: str) -> str | None:
    """Optional defaults; override with ``PYTH_FEED_ID_{ASSET}`` env (uppercase asset)."""
    raw = os.getenv(f"PYTH_FEED_ID_{asset.upper()}")
    if raw and raw.strip():
        return raw.strip().lower().removeprefix("0x")
    # Mainnet Crypto.*/USD (Hermes ``v2/price_feeds?query=...``); override via env if needed.
    defaults = {
        "btc": "e62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
        "eth": "ff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
        "sol": "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
    }
    return defaults.get(asset.lower())
