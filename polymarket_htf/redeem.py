"""
Redeem resolved **standard** CTF positions (EOA signer == token holder).

Adapted from the ``polymarket_btc5m`` project pattern: Data API positions + Polygon
``redeemPositions``. Neg-risk markets are skipped.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from web3 import Web3

from polymarket_htf.config_env import (
    ensure_certifi_ssl_env,
    polygon_rpc_url,
)
from polymarket_htf.positions_api import fetch_positions

ensure_certifi_ssl_env()
CTF_ADDRESS = Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
USDC_E_ADDRESS = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
ZERO_BYTES32 = bytes(32)
INDEX_SETS_BINARY: list[int] = [1, 2]

CTF_REDEEM_ABI = [
    {
        "name": "redeemPositions",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "outputs": [],
    }
]


def _sanitize_pk(raw: str) -> str:
    s = raw.strip()
    if s.startswith("0x"):
        s = s[2:]
    return s


def private_key_from_env() -> str | None:
    for k in ("POLYMARKET_PRIVATE_KEY", "POLYGON_PRIVATE_KEY"):
        v = os.getenv(k)
        if v and str(v).strip():
            return _sanitize_pk(str(v))
    return None


def funder_address() -> str | None:
    raw = os.getenv("POLYMARKET_FUNDER_ADDRESS") or os.getenv("POLYMARKET_FUNDER")
    if not raw or not str(raw).strip():
        return None
    return Web3.to_checksum_address(str(raw).strip())


def signer_address() -> str:
    pk = private_key_from_env()
    if not pk:
        raise RuntimeError("Set POLYMARKET_PRIVATE_KEY or POLYGON_PRIVATE_KEY.")
    w3 = Web3()
    return Web3.to_checksum_address(w3.eth.account.from_key("0x" + pk).address)


def redeem_query_address() -> str:
    pk = private_key_from_env()
    if not pk:
        raise RuntimeError("Set POLYMARKET_PRIVATE_KEY or POLYGON_PRIVATE_KEY.")
    fd = funder_address()
    if fd:
        return fd
    return signer_address()


def fetch_redeemable_positions(user: str, *, limit_per_page: int = 100, max_pages: int = 50) -> list[dict[str, Any]]:
    return fetch_positions(
        user,
        redeemable=True,
        limit_per_page=limit_per_page,
        max_pages=max_pages,
    )


def _condition_id_bytes(pos: dict[str, Any]) -> bytes:
    cid = pos.get("conditionId") or pos.get("condition_id")
    if not cid:
        raise ValueError("position missing conditionId")
    h = str(cid).strip()
    if not h.startswith("0x"):
        h = "0x" + h
    return Web3.to_bytes(hexstr=h)


def _is_neg_risk(pos: dict[str, Any]) -> bool:
    v = pos.get("negativeRisk")
    if v is None:
        v = pos.get("negative_risk")
    return bool(v)


@dataclass
class RedeemItemResult:
    condition_id: str
    title: str
    ok: bool
    tx_hash: str | None
    error: str | None


def redeem_positions_standard_eoa(
    positions: list[dict[str, Any]],
    *,
    dry_run: bool = True,
    holder: str | None = None,
) -> list[RedeemItemResult]:
    pk_raw = private_key_from_env()
    if not pk_raw:
        raise RuntimeError("Missing private key in environment.")
    pk = "0x" + pk_raw if not pk_raw.startswith("0x") else pk_raw
    holder_c = Web3.to_checksum_address(holder) if holder else redeem_query_address()
    signer = signer_address()
    if holder_c.lower() != signer.lower():
        raise RuntimeError(
            "EOA redeem requires tokens in the signing wallet. "
            "Use Polymarket UI or relayer flow when funder ≠ signer."
        )

    w3 = Web3(Web3.HTTPProvider(polygon_rpc_url().strip()))
    if not w3.is_connected():
        raise RuntimeError("Could not connect to Polygon RPC (POLYGON_RPC_URL).")

    acct = w3.eth.account.from_key(pk)
    ctf = w3.eth.contract(address=CTF_ADDRESS, abi=CTF_REDEEM_ABI)
    results: list[RedeemItemResult] = []
    nonce_base = w3.eth.get_transaction_count(signer)
    idx = 0

    for pos in positions:
        cid_hex = str(pos.get("conditionId") or pos.get("condition_id") or "")
        title = str(pos.get("title") or pos.get("slug") or cid_hex[:16])
        if _is_neg_risk(pos):
            results.append(
                RedeemItemResult(
                    condition_id=cid_hex,
                    title=title,
                    ok=False,
                    tx_hash=None,
                    error="negativeRisk — skipped",
                )
            )
            continue
        try:
            cond = _condition_id_bytes(pos)
        except Exception as e:
            results.append(
                RedeemItemResult(
                    condition_id=cid_hex,
                    title=title,
                    ok=False,
                    tx_hash=None,
                    error=str(e),
                )
            )
            continue

        try:
            if dry_run:
                nonce = nonce_base + idx
            else:
                nonce = w3.eth.get_transaction_count(signer)
            tx = ctf.functions.redeemPositions(
                USDC_E_ADDRESS,
                ZERO_BYTES32,
                cond,
                INDEX_SETS_BINARY,
            ).build_transaction({"from": signer, "chainId": 137, "nonce": nonce})
            gas = w3.eth.estimate_gas(tx)
            tx["gas"] = int(gas * 1.2) + 50_000
            tx["gasPrice"] = w3.eth.gas_price

            if dry_run:
                results.append(RedeemItemResult(condition_id=cid_hex, title=title, ok=True, tx_hash=None, error=None))
                idx += 1
                continue

            signed = acct.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
            h = w3.eth.send_raw_transaction(raw)
            results.append(
                RedeemItemResult(condition_id=cid_hex, title=title, ok=True, tx_hash=w3.to_hex(h), error=None)
            )
            time.sleep(0.35)
        except Exception as e:
            results.append(
                RedeemItemResult(condition_id=cid_hex, title=title, ok=False, tx_hash=None, error=str(e))
            )

    return results


def redeem_all_for_user(*, dry_run: bool = True, holder: str | None = None) -> tuple[list[dict], list[RedeemItemResult]]:
    user = Web3.to_checksum_address(holder) if holder else redeem_query_address()
    positions = fetch_redeemable_positions(user)
    results = redeem_positions_standard_eoa(positions, dry_run=dry_run, holder=user)
    return positions, results


def filter_crypto_slugs(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep positions whose slug/title hints at btc/eth/sol updown markets."""
    keys = ("slug", "title", "eventSlug")
    hints = ("btc-updown", "eth-updown", "sol-updown")
    out = []
    for p in positions:
        blob = " ".join(str(p.get(k) or "") for k in keys).lower()
        if any(h in blob for h in hints):
            out.append(p)
    return out
