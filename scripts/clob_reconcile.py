#!/usr/bin/env python3
"""
Read-only **reconciliation** snapshot: Polymarket Data API positions vs CLOB open orders.

Uses the same wallet as :func:`polymarket_htf.redeem.redeem_query_address` and L2 CLOB client.
Exit ``0`` always unless argparse/connection errors — inspect JSON for drift (e.g. many open orders
with few on-chain positions is normal during ladders; zero positions with many opens may hint bugs).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="Positions + open CLOB orders snapshot.")
    p.add_argument("--json", action="store_true", help="single JSON object to stdout")
    args = p.parse_args()

    from polymarket_htf.clob_account import make_trading_clob_client
    from polymarket_htf.config_env import load_dotenv_files
    from polymarket_htf.positions_api import fetch_positions
    from polymarket_htf.redeem import redeem_query_address

    load_dotenv_files(project_root=ROOT)
    user = redeem_query_address()
    positions = fetch_positions(user, redeemable=None, limit_per_page=500, max_pages=3)
    pos_n = len(positions)

    client = make_trading_clob_client()
    oo = client.get_orders()
    open_n = len(oo) if isinstance(oo, list) else 0

    snap = {
        "kind": "clob_reconcile",
        "user": user,
        "positions_rows": pos_n,
        "open_orders": open_n,
        "positions_sample_keys": list(positions[0].keys())[:12] if positions else [],
    }
    if args.json:
        print(json.dumps(snap, indent=2, default=str))
    else:
        print(json.dumps(snap, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
