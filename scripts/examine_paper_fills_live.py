#!/usr/bin/env python3
"""
Compare recent **paper_fill** rows from ``watch_sweet_spot`` JSONL to **live** Gamma + CLOB context.

Use this to **examine** how real prices / liquidity differ from toy backtests (e.g. 0.5 mid) before
scaling live size. Does **not** place orders.

Example::

  python scripts/examine_paper_fills_live.py --journal var/watch_sweet_spot.jsonl --last 8

When ``POLYGON_PRIVATE_KEY`` (and builder keys if your account needs them) are set, also prints
best bid / ask and midpoint from the CLOB for the outcome token matching the paper side.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_midpoint(raw: object) -> float:
    if isinstance(raw, dict) and "mid" in raw:
        return float(raw["mid"])
    if isinstance(raw, (int, float)):
        return float(raw)
    return float(str(raw).strip())


def load_last_paper_fills(path: Path, last: int) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(o.get("kind", "")) == "paper_fill":
                rows.append(o)
    if last > 0:
        rows = rows[-last:]
    return rows


def clob_liquidity_summary(token_id: str) -> dict[str, Any] | None:
    try:
        from polymarket_htf.clob_account import make_trading_clob_client

        client = make_trading_clob_client()
        book = client.get_order_book(token_id)
        mid = _parse_midpoint(client.get_midpoint(token_id))
        best_bid = float(book.bids[0].price) if book.bids else None
        best_ask = float(book.asks[0].price) if book.asks else None
        min_sz = float(book.min_order_size or "1")
        tick = float(client.get_tick_size(token_id))
        return {
            "clob_ok": True,
            "mid": mid,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": (best_ask - best_bid) if best_bid is not None and best_ask is not None else None,
            "min_order_size": min_sz,
            "tick": tick,
        }
    except Exception as e:
        return {"clob_ok": False, "clob_error": f"{type(e).__name__}: {e}"}


def enrich_row(row: dict[str, Any], *, toy_yes_mid: float) -> dict[str, Any]:
    from polymarket_htf.gamma import (
        fetch_event_by_slug,
        gamma_clob_token_ids_up_down,
        gamma_entry_price_for_crt_side,
        gamma_yes_no_mids,
    )

    slug = str(row.get("slug", "")).strip()
    side = str(row.get("side", "")).strip().upper()
    out: dict[str, Any] = {
        "slug": slug,
        "side": side,
        "T": row.get("T"),
        "journal_ts": row.get("ts"),
        "retrace_frac": row.get("retrace_frac"),
    }
    if not slug:
        out["gamma_error"] = "missing slug"
        return out
    ev = fetch_event_by_slug(slug)
    if ev is None:
        out["gamma_error"] = "404_or_fetch_failed"
        return out
    mids = gamma_yes_no_mids(ev)
    entry = gamma_entry_price_for_crt_side(ev, side) if side in ("UP", "DOWN") else None
    out["gamma_yes_no_mids"] = mids
    out["gamma_side_entry_mid"] = entry
    toy_entry = float(toy_yes_mid) if side == "UP" else float(1.0 - toy_yes_mid)
    out["toy_side_entry_mid"] = toy_entry
    if entry is not None:
        out["delta_toy_minus_gamma"] = round(toy_entry - float(entry), 6)

    pair = gamma_clob_token_ids_up_down(ev)
    if pair and side in ("UP", "DOWN"):
        up_id, down_id = pair
        token_id = up_id if side == "UP" else down_id
        out["token_id"] = token_id
        out["clob"] = clob_liquidity_summary(token_id)
        clob_side = "up" if side == "UP" else "down"
        out["clob_smoke_hint"] = (
            f"python scripts/clob_smoke.py --token-id {token_id} --side {clob_side} --max-usd 1"
        )
    else:
        out["clob"] = None
        out["clob_smoke_hint"] = None
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Examine paper_fill rows vs Gamma/CLOB (no orders).")
    p.add_argument("--journal", type=Path, default=ROOT / "var" / "watch_sweet_spot.jsonl")
    p.add_argument("--last", type=int, default=6, help="last N paper_fill rows (0 = all)")
    p.add_argument("--toy-yes-mid", type=float, default=0.5, help="toy YES mid used to compare to Gamma side entry")
    p.add_argument("--json", action="store_true", help="print one JSON array instead of text")
    args = p.parse_args()

    from polymarket_htf.config_env import ensure_certifi_ssl_env, load_dotenv_files

    ensure_certifi_ssl_env()
    load_dotenv_files(project_root=ROOT)

    try:
        fills = load_last_paper_fills(args.journal.resolve(), int(args.last))
    except FileNotFoundError as e:
        print("error:", e, file=sys.stderr)
        return 2
    if not fills:
        print("no paper_fill rows in", args.journal, file=sys.stderr)
        return 1

    enriched = [enrich_row(r, toy_yes_mid=float(args.toy_yes_mid)) for r in fills]
    if args.json:
        print(json.dumps(enriched, indent=2, default=str))
        return 0

    print(f"# paper_fill examination (last {len(fills)} from {args.journal})")
    print(f"# toy YES mid = {args.toy_yes_mid} (DOWN toy complement)\n")
    for e in enriched:
        slug = e["slug"]
        print(f"## {slug}  side={e['side']}  T={e.get('T')}  journal_ts={e.get('journal_ts')}")
        if e.get("gamma_error"):
            print(f"  gamma: {e['gamma_error']}\n")
            continue
        print(f"  gamma_yes_no_mids: {e.get('gamma_yes_no_mids')}")
        print(f"  gamma_side_entry_mid: {e.get('gamma_side_entry_mid')}")
        if "delta_toy_minus_gamma" in e:
            print(f"  toy_side_mid - gamma_side_mid: {e['delta_toy_minus_gamma']}  (+ means toy cheaper than Gamma)")
        clob = e.get("clob")
        if clob is None:
            print("  clob: (no token ids)\n")
        elif not clob.get("clob_ok"):
            print(f"  clob: {clob.get('clob_error')}\n")
        else:
            print(
                f"  clob mid={clob.get('mid')} bid={clob.get('best_bid')} ask={clob.get('best_ask')} "
                f"spread={clob.get('spread')} min_sz={clob.get('min_order_size')} tick={clob.get('tick')}"
            )
            if e.get("clob_smoke_hint"):
                print(f"  tiny BUY dry-run: {e['clob_smoke_hint']}")
                print("  tiny BUY execute:  LIVE_TRADING_ENABLED=1  " + str(e["clob_smoke_hint"]) + "  --execute")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
