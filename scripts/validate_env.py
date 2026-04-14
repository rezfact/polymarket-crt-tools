#!/usr/bin/env python3
"""
Load repo ``.env`` and sanity-check common variables **without printing secret values**.

Usage::

  ./.venv313/bin/python scripts/validate_env.py
  ./.venv313/bin/python scripts/validate_env.py --telegram-getme
  ./.venv313/bin/python scripts/validate_env.py --pyth-sample
  ./.venv313/bin/python scripts/validate_env.py --polymarket-positions
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _secret_hint(_s: str | None) -> str:
    """Never log secret substrings — length only."""
    if not _s or not str(_s).strip():
        return "(empty)"
    return f"(set, len={len(str(_s).strip())})"


def _has(name: str) -> bool:
    import os

    v = os.getenv(name)
    return bool(v and str(v).strip())


def main() -> int:
    p = argparse.ArgumentParser(description="Validate .env without leaking secrets.")
    p.add_argument("--telegram-getme", action="store_true", help="call Telegram getMe (needs token)")
    p.add_argument("--pyth-sample", action="store_true", help="one small Pyth TV history request")
    p.add_argument(
        "--polymarket-positions",
        action="store_true",
        help="GET Data API /positions for POLYMARKET_FUNDER_ADDRESS or signer (read-only; not CLOB auth)",
    )
    args = p.parse_args()

    from polymarket_htf.config_env import load_dotenv_files

    load_dotenv_files(project_root=ROOT)

    import os

    import requests
    from web3 import Web3

    from polymarket_htf.config_env import (
        polygon_rpc_url_candidates,
        pyth_benchmarks_request_headers,
        tls_verify_requests,
    )
    from polymarket_htf.redeem import private_key_from_env, signer_address

    ok = 0
    warn = 0
    fail = 0

    def line(tag: str, status: str, detail: str = "") -> None:
        nonlocal ok, warn, fail
        if status == "OK":
            ok += 1
        elif status == "WARN":
            warn += 1
        else:
            fail += 1
        extra = f"  {detail}" if detail else ""
        print(f"[{status:4}] {tag}{extra}")

    # --- Telegram ---
    if _has("TELEGRAM_BOT_TOKEN") and _has("TELEGRAM_CHAT_ID"):
        line("TELEGRAM_BOT_TOKEN", "OK", _secret_hint(os.getenv("TELEGRAM_BOT_TOKEN")))
        line("TELEGRAM_CHAT_ID", "OK", "(set)")
    elif _has("TELEGRAM_BOT_TOKEN") or _has("TELEGRAM_CHAT_ID"):
        line("Telegram", "WARN", "need both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    else:
        line("Telegram", "WARN", "not configured (optional unless you use notify scripts)")

    if args.telegram_getme:
        tok = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        if not tok:
            line("telegram getMe", "FAIL", "no TELEGRAM_BOT_TOKEN")
        else:
            url = f"https://api.telegram.org/bot{tok}/getMe"
            try:
                r = requests.get(url, timeout=20, verify=tls_verify_requests())
                data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                if r.status_code == 200 and data.get("ok"):
                    u = (data.get("result") or {}).get("username", "?")
                    line("telegram getMe", "OK", f"bot @{u}")
                else:
                    line("telegram getMe", "FAIL", f"HTTP {r.status_code}")
            except Exception as e:
                line("telegram getMe", "FAIL", str(e)[:80])

    # --- Polygon RPC ---
    urls = polygon_rpc_url_candidates()
    connected = False
    chain = None
    last_err = ""
    used_url = ""
    for u in urls[:6]:
        try:
            w3 = Web3(Web3.HTTPProvider(u.strip(), request_kwargs={"timeout": 15}))
            if w3.is_connected():
                connected = True
                chain = w3.eth.chain_id
                used_url = u.strip()
                break
        except Exception as e:
            last_err = str(e)[:60]
    if connected:
        line("POLYGON_RPC", "OK", f"chain_id={chain} rpc_ok=1")
    else:
        line("POLYGON_RPC", "FAIL", last_err or "no endpoint connected")

    # --- Private key (redeem) ---
    pk = private_key_from_env()
    if pk:
        try:
            addr = signer_address()
            line("POLYGON_PRIVATE_KEY / POLYMARKET_PRIVATE_KEY", "OK", f"signer={addr}")
        except Exception as e:
            line("Private key parse", "FAIL", str(e)[:80])
    else:
        line("POLYGON_PRIVATE_KEY", "WARN", "not set (required for redeem --execute)")

    # --- Polymarket builder (presence only) ---
    for k in ("POLY_BUILDER_API_KEY", "POLY_BUILDER_SECRET", "POLY_BUILDER_PASSPHRASE"):
        if _has(k):
            line(k, "OK", _secret_hint(os.getenv(k)))
        else:
            line(k, "WARN", "empty (ok if not using CLOB client yet)")
    if _has("POLYMARKET_FUNDER_ADDRESS"):
        line("POLYMARKET_FUNDER_ADDRESS", "OK", "(set)")
    if _has("POLYMARKET_SIGNATURE_TYPE"):
        line("POLYMARKET_SIGNATURE_TYPE", "OK", os.getenv("POLYMARKET_SIGNATURE_TYPE", "").strip())

    # --- Pyth API key header build ---
    h = pyth_benchmarks_request_headers()
    if "Authorization" in h or any(k.lower().startswith("x-") for k in h):
        line("Pyth auth headers", "OK", "extra header(s) attached for Benchmarks TV")
    else:
        line("Pyth auth headers", "OK", "default User-Agent only")

    if args.polymarket_positions:
        from polymarket_htf.positions_api import polymarket_positions_api_ping
        from polymarket_htf.redeem import redeem_query_address

        try:
            user = redeem_query_address()
        except Exception as e:
            line("Polymarket Data API /positions", "WARN", f"skip (no query address): {str(e)[:80]}")
        else:
            try:
                good, detail = polymarket_positions_api_ping(user)
                st = "OK" if good else "FAIL"
                line("Polymarket Data API /positions", st, f"user={user} {detail}")
            except Exception as e:
                line("Polymarket Data API /positions", "FAIL", str(e)[:120])

    if args.pyth_sample:
        from polymarket_htf.config_env import pyth_benchmarks_tv_history_url

        import urllib.parse

        base = pyth_benchmarks_tv_history_url().rstrip("?")
        q = urllib.parse.urlencode(
            {"symbol": "Crypto.BTC/USD", "resolution": "15", "from": "1700000000", "to": "1700000900"}
        )
        url = f"{base}?{q}"
        try:
            r = requests.get(url, headers=h, timeout=30, verify=tls_verify_requests())
            r.raise_for_status()
            j = r.json()
            st = j.get("s") if isinstance(j, dict) else None
            line("Pyth TV history sample", "OK", f"status={st}")
        except Exception as e:
            line("Pyth TV history sample", "FAIL", str(e)[:120])

    # --- CRT_MONTH dates ---
    start = os.getenv("CRT_MONTH_START", "").strip()
    end = os.getenv("CRT_MONTH_END", "").strip()
    if start or end:
        try:
            if start:
                datetime.fromisoformat(start.replace("Z", "+00:00"))
            if end:
                datetime.fromisoformat(end.replace("Z", "+00:00"))
            line("CRT_MONTH_START/END", "OK", f"{start!r} .. {end!r}")
        except Exception:
            line("CRT_MONTH_START/END", "FAIL", "unparseable ISO date")
    else:
        line("CRT_MONTH_START/END", "WARN", "unset (ok for live-only .env)")

    print()
    print(f"summary: OK={ok} WARN={warn} FAIL={fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
