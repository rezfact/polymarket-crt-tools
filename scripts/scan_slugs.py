#!/usr/bin/env python3
"""Probe Gamma for active btc/eth/sol up/down slugs (5m or 15m grid)."""
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
    p.add_argument("--tf", type=int, default=15, choices=[5, 15], help="Polymarket window minutes")
    p.add_argument("--include-inactive", action="store_true", help="Return first slug with markets even if closed")
    args = p.parse_args()

    from polymarket_htf.gamma import fetch_event_by_slug, gamma_market_headline, scan_all_assets

    slugs = scan_all_assets(
        tf_minutes=args.tf,
        require_active=not args.include_inactive,
        neighbor_windows=6,
    )
    detail = {}
    for asset, slug in slugs.items():
        if not slug:
            detail[asset] = {"slug": None}
            continue
        ev = fetch_event_by_slug(slug)
        detail[asset] = {"slug": slug, "headline": gamma_market_headline(ev or {})}
    print(json.dumps(detail, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
