#!/usr/bin/env python3
"""Summarize a dryrun JSONL: sides, reasons, slug vs asset, time gaps (sanity check)."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("journal", type=Path, help="path to JSONL (e.g. var/dryrun_1h_session.jsonl)")
    args = p.parse_args()
    path = args.journal
    if not path.is_file():
        print(f"error: not a file: {path}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"error: line {i}: {e}", file=sys.stderr)
                return 3

    n = len(rows)
    kinds = Counter(r.get("kind") for r in rows)
    sides = Counter()
    reasons = Counter()
    bad_slug = 0
    for r in rows:
        if r.get("kind") != "dryrun":
            continue
        asset = r.get("asset")
        slug = r.get("slug") or ""
        sig = r.get("signal") or {}
        if isinstance(sig, dict):
            sides[str(sig.get("side", "?"))] += 1
            reasons[str(sig.get("reason", "?"))] += 1
        if asset and slug and not str(slug).startswith(f"{asset}-"):
            bad_slug += 1

    print(f"file={path.resolve()}")
    print(f"lines={n} kinds={dict(kinds)}")
    print(f"signal.side counts: {dict(sides)}")
    print("top reasons:")
    for reason, c in reasons.most_common(12):
        print(f"  {c:4d}  {reason}")
    if bad_slug:
        print(f"warn: slug prefix mismatches asset: {bad_slug}")
    else:
        print("slug prefix vs asset: ok")

    sc = int(reasons.get("crt_sweep_conflict", 0))
    nd = int(reasons.get("crt_no_distribution_inside", 0))
    nm = int(reasons.get("crt_no_manipulation", 0))
    if sc + nd + nm >= max(3, n // 2):
        print(
            "\nhint: many structural SKIPs — try fewer filters, e.g.\n"
            "  ./.venv313/bin/python scripts/dryrun.py --once --price-source pyth --log-on-bar-change \\\n"
            "    --crt-no-htf-filter --crt-sweep-conflict prefer_bull\n"
            "or: CRT_NO_HTF=1 CRT_SWEEP=prefer_bull ./scripts/run_dryrun_1h.sh"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
