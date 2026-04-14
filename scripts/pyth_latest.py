#!/usr/bin/env python3
"""Print Hermes latest aggregate price + confidence (Pyth) for btc | eth | sol."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="Hermes latest_price_feeds (price + conf + publish_time).")
    p.add_argument("--asset", default="btc", help="btc | eth | sol (default feed ids; override PYTH_FEED_ID_* )")
    p.add_argument("--feed-id", default=None, help="64-hex feed id (overrides --asset defaults)")
    args = p.parse_args()

    from polymarket_htf.hermes_latest import default_feed_id_for_asset, fetch_latest_price_feeds

    fid = (args.feed_id or default_feed_id_for_asset(args.asset) or "").strip().lower().removeprefix("0x")
    if not fid:
        print("error: no feed id (set PYTH_FEED_ID_<ASSET> or use --feed-id)", file=sys.stderr)
        return 2
    rows = fetch_latest_price_feeds([fid])
    if not rows:
        print("error: empty Hermes response", file=sys.stderr)
        return 3
    r = rows[0]
    ts = datetime.fromtimestamp(r.publish_time, tz=timezone.utc).isoformat()
    print(f"feed_id={r.feed_id}")
    print(f"price_usd={r.price:.8g}  conf_usd={r.conf:.8g}  publish_time_utc={ts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
