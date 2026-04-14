#!/usr/bin/env python3
"""
Redeem resolved Polymarket positions (EOA: signer wallet holds tokens).

Default: dry-run (gas estimate path). Use ``--execute`` to broadcast.

``--crypto-only``: only redeem rows whose slug/title looks like btc/eth/sol updown.
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
    p = argparse.ArgumentParser()
    p.add_argument("--execute", action="store_true", help="submit txs (default dry-run)")
    p.add_argument("--crypto-only", action="store_true", help="filter to btc/eth/sol updown-like positions")
    p.add_argument("--journal", type=Path, default=None, help="append JSONL log of redeem attempts")
    args = p.parse_args()

    from polymarket_htf.journal import append_jsonl, utc_now_iso
    from polymarket_htf.redeem import (
        fetch_redeemable_positions,
        filter_crypto_slugs,
        redeem_positions_standard_eoa,
        redeem_query_address,
    )

    dry = not args.execute
    user = redeem_query_address()
    positions = fetch_redeemable_positions(user)
    if args.crypto_only:
        positions = filter_crypto_slugs(positions)
    results = redeem_positions_standard_eoa(positions, dry_run=dry, holder=user)

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
        print(json.dumps(line, default=str))
        if args.journal:
            append_jsonl(args.journal, line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
