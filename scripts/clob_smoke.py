#!/usr/bin/env python3
"""
CLOB **smoke test**: derive L2 creds, read book, optionally post a small **BUY** GTC limit on **Up**.

Safety gates (all required for real submit):

- ``--execute``
- ``LIVE_TRADING_ENABLED=1`` in environment (``.env`` ok after ``load_dotenv_files``)
- No file at ``LIVE_KILL_SWITCH_PATH`` when that env is set

Notional cap: ``LIVE_SMOKE_MAX_USD`` (default ``3``) — uses best bid / mid to pick price and obeys
``min_order_size`` from the order book.

Dry-run (default): prints plan only (no order).
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
    p = argparse.ArgumentParser(description="Polymarket CLOB smoke (plan or tiny BUY).")
    p.add_argument("--execute", action="store_true", help="submit order (requires LIVE_TRADING_ENABLED=1)")
    p.add_argument("--max-usd", type=float, default=None, help="override LIVE_SMOKE_MAX_USD for this run")
    p.add_argument("--asset", default="btc", help="btc | eth | sol (Gamma up/down slug)")
    p.add_argument("--tf", type=int, default=15, choices=[5, 15])
    p.add_argument("--side", choices=["up", "down"], default="up", help="which outcome token to BUY")
    p.add_argument("--token-id", type=str, default=None, help="override Gamma discovery: raw CLOB token id")
    p.add_argument("--cancel", type=str, default=None, metavar="ORDER_ID", help="cancel this order id then exit")
    args = p.parse_args()

    from polymarket_htf.config_env import (
        live_kill_switch_path,
        live_smoke_max_usd,
        live_trading_enabled,
        live_trading_paused_by_file,
        load_dotenv_files,
    )
    from polymarket_htf.gamma import (
        build_updown_slug,
        discover_updown_slug,
        fetch_event_by_slug,
        gamma_clob_token_ids_up_down,
    )

    load_dotenv_files(project_root=ROOT)

    from polymarket_htf.clob_account import make_trading_clob_client
    from polymarket_htf.clob_plan import plan_buy_limit_notional
    from polymarket_htf.journal import append_jsonl_with_eval_mirror, utc_now_iso
    from polymarket_htf.redeem import redeem_query_address

    client = make_trading_clob_client()

    if args.cancel:
        client.cancel(order_id=args.cancel)
        print(json.dumps({"ok": True, "cancelled": args.cancel}, default=str))
        return 0

    max_usd = float(args.max_usd) if args.max_usd is not None else float(live_smoke_max_usd())

    if args.token_id:
        token_id = str(args.token_id).strip()
        slug = None
    else:
        from polymarket_htf.assets import normalize_asset

        a = normalize_asset(args.asset)
        slug = discover_updown_slug(a, tf_minutes=int(args.tf))
        if not slug:
            print("error: no active Gamma slug found for asset/tf", file=sys.stderr)
            return 2
        ev = fetch_event_by_slug(slug)
        if not ev:
            print("error: Gamma fetch failed for slug", slug, file=sys.stderr)
            return 2
        pair = gamma_clob_token_ids_up_down(ev)
        if not pair:
            print("error: could not parse clobTokenIds from Gamma event", file=sys.stderr)
            return 2
        up_id, down_id = pair
        token_id = up_id if args.side == "up" else down_id

    addr = redeem_query_address()
    price, size, meta = plan_buy_limit_notional(client=client, token_id=token_id, max_usd=max_usd)
    plan = {
        "kind": "clob_smoke_plan",
        "ts": utc_now_iso(),
        "user": addr,
        "slug": slug,
        "token_id": token_id,
        "side": args.side,
        "price": price,
        "size": size,
        "approx_usd": round(price * size, 6),
        "max_usd": max_usd,
        **meta,
    }
    print(json.dumps(plan, indent=2, default=str))

    if not args.execute:
        print("\n(dry-run: no order sent; use --execute + LIVE_TRADING_ENABLED=1 to submit)", file=sys.stderr)
        return 0

    if not live_trading_enabled():
        print("error: set LIVE_TRADING_ENABLED=1 to allow --execute", file=sys.stderr)
        return 1
    if live_trading_paused_by_file():
        print(f"error: kill-switch file exists: {live_kill_switch_path()}", file=sys.stderr)
        return 1

    from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions
    from py_clob_client.order_builder.constants import BUY

    order_args = OrderArgs(token_id=token_id, price=float(price), size=float(size), side=BUY)
    resp = client.create_and_post_order(order_args, PartialCreateOrderOptions())
    out = {"kind": "clob_smoke_order", "ts": utc_now_iso(), "response": resp}
    print(json.dumps(out, indent=2, default=str))

    append_jsonl_with_eval_mirror(ROOT / "var" / "live_smoke.jsonl", out, pipeline="live_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
