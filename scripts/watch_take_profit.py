#!/usr/bin/env python3
"""
Poll Polymarket Data API positions and compute **take-profit ladder** sells (premium return %).

Default: **dry-run** (log planned share sizes). **CLOB sell is not wired** in this repo yet;
use output to place orders manually or connect ``py-clob-client`` later.

Example (500% → sell 50% of remaining, 1000% → sell all remaining)::

    python scripts/watch_take_profit.py --tiers "500:0.5,1000:1" --interval 20

State file (which tiers already fired)::

    var/take_profit_state.json

Advance state without trading (simulates fills for testing persistence)::

    python scripts/watch_take_profit.py --tiers "500:0.5,1000:1" --advance-state
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fetch_open_positions(user: str):
    from polymarket_htf.positions_api import fetch_positions

    try:
        return fetch_positions(user, redeemable=False)
    except Exception:
        return fetch_positions(user, redeemable=None)


def _tradeable_row(pos: dict) -> bool:
    from polymarket_htf.take_profit_ladder import position_mark

    try:
        sz = float(pos.get("size") or 0)
    except (TypeError, ValueError):
        return False
    if sz <= 0:
        return False
    if pos.get("redeemable") is True:
        return False
    return position_mark(pos) is not None


def main() -> int:
    p = argparse.ArgumentParser(description="Take-profit ladder watcher (planning + optional state)")
    p.add_argument(
        "--tiers",
        type=str,
        default=None,
        help='e.g. "500:0.5,1000:1" (+500%% premium vs avg entry → sell 50%% of remaining; +1000%% → sell rest)',
    )
    p.add_argument(
        "--state",
        type=Path,
        default=Path("var/take_profit_state.json"),
        help="JSON map position_key → list[bool] fired per tier",
    )
    p.add_argument("--interval", type=float, default=30.0, help="seconds between polls (loop mode)")
    p.add_argument("--once", action="store_true", help="single poll then exit")
    p.add_argument(
        "--advance-state",
        action="store_true",
        help="after planning, write fired flags as if sells filled (no CLOB; for testing)",
    )
    p.add_argument("--crypto-only", action="store_true", help="only rows whose slug/title looks btc/eth/sol updown")
    args = p.parse_args()

    from polymarket_htf.config_env import load_dotenv_files
    from polymarket_htf.redeem import filter_crypto_slugs, redeem_query_address
    from polymarket_htf.take_profit_ladder import (
        load_ladder_state,
        merge_fired_for_tiers,
        parse_tiers_spec,
        plan_ladder_exits,
        position_avg_entry,
        position_key,
        position_mark,
        save_ladder_state,
    )
    import os

    load_dotenv_files(project_root=ROOT)
    spec = args.tiers or os.getenv("TAKE_PROFIT_TIERS", "").strip()
    if not spec:
        print("Set --tiers or TAKE_PROFIT_TIERS (e.g. 500:0.5,1000:1)", file=sys.stderr)
        return 2
    tiers = parse_tiers_spec(spec)
    n = len(tiers)
    user = redeem_query_address()
    state_path = args.state if args.state.is_absolute() else ROOT / args.state

    def tick() -> None:
        rows = _fetch_open_positions(user)
        if args.crypto_only:
            rows = filter_crypto_slugs(rows)
        state = load_ladder_state(state_path)
        for pos in rows:
            if not _tradeable_row(pos):
                continue
            key = position_key(pos)
            avg = position_avg_entry(pos)
            mark = position_mark(pos)
            if avg is None or mark is None:
                continue
            try:
                size = float(pos.get("size") or 0)
            except (TypeError, ValueError):
                continue
            fired = state.get(key, [False] * n)
            if len(fired) != n:
                fired = (list(fired) + [False] * n)[:n]
            planned, new_fired = plan_ladder_exits(
                avg_entry=avg,
                mark=mark,
                position_size=size,
                tiers=tiers,
                fired=fired,
            )
            if not planned:
                continue
            for pl in planned:
                line = {
                    "kind": "take_profit_plan",
                    "position_key": key,
                    "title": pos.get("title") or pos.get("slug"),
                    "avg_entry": avg,
                    "mark": mark,
                    "size": size,
                    "premium_return_pct": pl.premium_return_pct,
                    "tier_index": pl.tier_index,
                    "threshold_pct": pl.threshold_pct,
                    "sell_fraction": pl.sell_fraction,
                    "shares_to_sell": pl.shares,
                    "dry_run": True,
                }
                print(json.dumps(line, default=str))
            if args.advance_state:
                merge_fired_for_tiers(state, key, n, new_fired)
        if args.advance_state:
            save_ladder_state(state_path, state)

    tick()
    if args.once:
        return 0
    while True:
        time.sleep(max(1.0, args.interval))
        tick()


if __name__ == "__main__":
    raise SystemExit(main())
