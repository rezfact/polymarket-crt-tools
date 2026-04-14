"""
Polygon **BTC/USD Chainlink** latest (O3-style strike reference for live monitoring).

Read-only; uses ``web3`` + env from :mod:`polymarket_htf.config_env`.
Retries transient RPC failures and cycles through :func:`polygon_rpc_url_candidates`
when no explicit ``rpc_url`` is passed.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChainlinkBtcUsd:
    price: float
    decimals: int
    round_id: int
    updated_at: int


def _agg_v3_abi() -> list[dict[str, Any]]:
    return [
        {
            "inputs": [],
            "name": "decimals",
            "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [],
            "name": "latestRoundData",
            "outputs": [
                {"internalType": "uint80", "name": "roundId", "type": "uint80"},
                {"internalType": "int256", "name": "answer", "type": "int256"},
                {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
                {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
                {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"},
            ],
            "stateMutability": "view",
            "type": "function",
        },
    ]


def _rpc_transient(exc: BaseException) -> bool:
    try:
        import requests
    except ImportError:
        requests = None  # type: ignore[assignment]
    if requests is not None and isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    ):
        return True
    msg = str(exc).lower()
    if "connection reset" in msg or "connection aborted" in msg or "timeout" in msg:
        return True
    if "405" in msg or "429" in msg or "502" in msg or "503" in msg or "504" in msg:
        return True
    return False


def _read_chainlink_once(*, rpc: str, feed: str, timeout: int) -> ChainlinkBtcUsd:
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": timeout}))
    c = w3.eth.contract(address=Web3.to_checksum_address(feed), abi=_agg_v3_abi())
    dec = int(c.functions.decimals().call())
    rid, ans, _sa, upd, _air = c.functions.latestRoundData().call()
    price = float(int(ans)) * (10.0**-dec)
    return ChainlinkBtcUsd(price=price, decimals=dec, round_id=int(rid), updated_at=int(upd))


def fetch_chainlink_btc_usd(
    *,
    rpc_url: str | None = None,
    feed_address: str | None = None,
    timeout: int = 25,
    attempts_per_rpc: int = 4,
) -> ChainlinkBtcUsd:
    from polymarket_htf.config_env import (
        polygon_chainlink_btc_usd_feed,
        polygon_rpc_url_candidates,
    )

    if rpc_url:
        candidates = [rpc_url.strip()]
    else:
        candidates = polygon_rpc_url_candidates()
    feed = feed_address or polygon_chainlink_btc_usd_feed()
    last_exc: BaseException | None = None
    for rpc in candidates:
        for i in range(max(1, int(attempts_per_rpc))):
            try:
                return _read_chainlink_once(rpc=rpc, feed=feed, timeout=timeout)
            except BaseException as e:  # noqa: BLE001 — classify for retry / next RPC
                last_exc = e
                if not _rpc_transient(e):
                    raise
                if i >= attempts_per_rpc - 1:
                    break
                time.sleep(min(8.0, 0.35 * (2**i) + random.random() * 0.2))
    assert last_exc is not None
    raise last_exc
