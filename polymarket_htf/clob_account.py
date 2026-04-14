"""
Polymarket **CLOB** trading client from environment (``py-clob-client``).

Uses the same key / funder conventions as :mod:`polymarket_htf.redeem`.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from web3 import Web3

from polymarket_htf.config_env import poly_clob_host
from polymarket_htf.redeem import private_key_from_env

if TYPE_CHECKING:
    pass


def _sanitize_pk(raw: str) -> str:
    s = raw.strip()
    if s.startswith("0x"):
        s = s[2:]
    return s


def clob_private_key_hex() -> str:
    pk = private_key_from_env()
    if not pk:
        raise RuntimeError("Set POLYGON_PRIVATE_KEY or POLYMARKET_PRIVATE_KEY for CLOB signing.")
    return _sanitize_pk(pk)


def clob_funder_address() -> str | None:
    raw = os.getenv("POLYMARKET_FUNDER_ADDRESS") or os.getenv("POLYMARKET_FUNDER")
    if not raw or not str(raw).strip():
        return None
    return Web3.to_checksum_address(str(raw).strip())


def clob_signature_type() -> int:
    raw = os.getenv("POLYMARKET_SIGNATURE_TYPE")
    if raw is None or not str(raw).strip():
        return 0
    return int(str(raw).strip())


def clob_builder_config() -> Any | None:
    """Return ``BuilderConfig`` if all three builder fields are set; else ``None``."""
    k = (os.getenv("POLY_BUILDER_API_KEY") or "").strip()
    s = (os.getenv("POLY_BUILDER_SECRET") or "").strip()
    p = (os.getenv("POLY_BUILDER_PASSPHRASE") or "").strip()
    if not (k and s and p):
        return None
    from py_builder_signing_sdk.config import BuilderConfig
    from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds

    return BuilderConfig(local_builder_creds=BuilderApiKeyCreds(key=k, secret=s, passphrase=p))


def make_trading_clob_client(*, chain_id: int = 137):
    """
    Level-2 authenticated :class:`py_clob_client.client.ClobClient` (derive API creds each call).

    ``funder`` defaults to the signer address when unset (EOA-style); Polymarket proxy accounts
    should set ``POLYMARKET_FUNDER_ADDRESS`` explicitly.
    """
    from py_clob_client.client import ClobClient

    host = poly_clob_host()
    pk = clob_private_key_hex()
    key = "0x" + pk if not pk.startswith("0x") else pk
    temp = ClobClient(host, key=key, chain_id=chain_id)
    creds = temp.create_or_derive_api_creds()
    fd = clob_funder_address()
    if fd is None:
        fd = Web3.to_checksum_address(temp.get_address())
    bc = clob_builder_config()
    return ClobClient(
        host,
        key=key,
        chain_id=chain_id,
        creds=creds,
        signature_type=clob_signature_type(),
        funder=fd,
        builder_config=bc,
    )
