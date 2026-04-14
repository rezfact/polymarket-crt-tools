#!/usr/bin/env python3
"""
Hourly (or cron) **redeem** pass + optional **Telegram** summary.

Same redemption flow as ``scripts/redeem_wins.py``; intended for ``cron`` / ``systemd.timer``.

Examples::

  ./.venv313/bin/python scripts/redeem_hourly.py
  ./.venv313/bin/python scripts/redeem_hourly.py --execute --crypto-only --telegram
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_htf.config_env import load_dotenv_files


def main() -> int:
    p = argparse.ArgumentParser(description="Redeem Polymarket positions + optional Telegram summary.")
    p.add_argument("--execute", action="store_true", help="broadcast txs (default dry-run)")
    p.add_argument("--crypto-only", action="store_true", help="only btc/eth/sol updown-like slugs")
    p.add_argument("--journal", type=Path, default=None, help="append JSONL lines like redeem_wins")
    p.add_argument(
        "--telegram",
        action="store_true",
        help="send Telegram summary (needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)",
    )
    args = p.parse_args()

    load_dotenv_files(project_root=ROOT)

    from polymarket_htf.journal import append_jsonl, utc_now_iso
    from polymarket_htf.redeem import (
        fetch_redeemable_positions,
        filter_crypto_slugs,
        redeem_positions_standard_eoa,
        redeem_query_address,
    )
    from polymarket_htf.telegram_notify import send_telegram_message, telegram_credentials_ok

    dry = not args.execute
    user = redeem_query_address()
    positions = fetch_redeemable_positions(user)
    if args.crypto_only:
        positions = filter_crypto_slugs(positions)
    results = redeem_positions_standard_eoa(positions, dry_run=dry, holder=user)

    ok_n = sum(1 for r in results if r.ok)
    fail_n = len(results) - ok_n
    lines_out = []
    for r in results:
        line = {
            "kind": "redeem",
            "ts": utc_now_iso(),
            "dry_run": dry,
            "title": r.title,
            "ok": r.ok,
            "tx_hash": r.tx_hash,
            "error": r.error,
        }
        lines_out.append(line)
        print(json.dumps(line, default=str))
        if args.journal:
            append_jsonl(args.journal, line)

    summary = (
        f"redeem_hourly dry_run={dry} positions={len(positions)} results={len(results)} "
        f"ok={ok_n} fail={fail_n}"
    )
    print(summary, flush=True)

    if args.telegram:
        if not telegram_credentials_ok():
            print("warn: --telegram set but missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID", file=sys.stderr)
        else:
            body = [summary, ""]
            for r in results[:15]:
                st = "OK" if r.ok else "FAIL"
                tx = (r.tx_hash or "")[:18]
                body.append(f"{st} {r.title[:60]} tx={tx} err={r.error or '-'}")
            if len(results) > 15:
                body.append(f"... +{len(results) - 15} more")
            if not send_telegram_message("\n".join(body)):
                print("warn: Telegram sendMessage failed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
