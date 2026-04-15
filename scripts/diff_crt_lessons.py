#!/usr/bin/env python3
"""
Compare two **CRT lessons** JSON files from ``scripts/crt_signal_history.py``.

Supports:
- **Single-asset** shape (top-level ``summary`` / ``tuning_dig``)
- **Multi-asset** shape (``per_asset`` map); diffs each asset in the intersection, or ``--asset`` only.

Example::

  ./.venv/bin/python scripts/diff_crt_lessons.py \\
    var/crt_lessons_loose_90d.json var/crt_lessons_loose_plus_90d.json

  ./.venv/bin/python scripts/diff_crt_lessons.py baseline.json experiment.json --asset btc
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def _per_asset_map(lessons: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pa = lessons.get("per_asset")
    if isinstance(pa, dict) and pa:
        return {str(k): v for k, v in pa.items() if isinstance(v, dict)}
    meta = lessons.get("meta") or {}
    asset = str(meta.get("asset") or "single")
    return {asset: lessons}


def _pct(part: int, whole: int) -> str:
    if whole <= 0:
        return "n/a"
    return f"{100.0 * part / whole:.2f}%"


def _side_summary(summary: dict[str, Any]) -> dict[str, int]:
    cs = summary.get("counts_by_side") or {}
    if not isinstance(cs, dict):
        return {}
    return {k: int(v) for k, v in cs.items() if str(k) in ("UP", "DOWN", "SKIP")}


def _reason_counts(summary: dict[str, Any]) -> dict[str, int]:
    cr = summary.get("counts_by_reason") or {}
    if not isinstance(cr, dict):
        return {}
    return {str(k): int(v) for k, v in cr.items()}


def _print_block(title: str, lines: list[str]) -> None:
    print(title)
    for ln in lines:
        print(ln)


def diff_one_asset(
    *,
    label_a: str,
    label_b: str,
    a: dict[str, Any],
    b: dict[str, Any],
    asset: str,
) -> None:
    sa = a.get("summary") or {}
    sb = b.get("summary") or {}
    if not isinstance(sa, dict) or not isinstance(sb, dict):
        print(f"  [{asset}] missing summary in one file", file=sys.stderr)
        return

    na = int(sa.get("bars") or 0)
    nb = int(sb.get("bars") or 0)
    if na != nb:
        print(f"  [{asset}] warn: bars differ A={na} B={nb} (compare rates, not raw deltas)", file=sys.stderr)

    ca, cb = _side_summary(sa), _side_summary(sb)
    lines = [
        f"  bars: {na}",
        f"  side counts: A={ca}  B={cb}",
    ]
    for side in ("UP", "DOWN", "SKIP"):
        va, vb = ca.get(side, 0), cb.get(side, 0)
        d = vb - va
        lines.append(
            f"  {side}: A={va} ({_pct(va, na)})  B={vb} ({_pct(vb, nb)})  Δ={d:+}"
        )
    _print_block(f"## {asset} — sides ({label_a} → {label_b})", lines)

    ra, rb = _reason_counts(sa), _reason_counts(sb)
    keys = sorted(set(ra) | set(rb))
    rlines = []
    for k in keys:
        va, vb = ra.get(k, 0), rb.get(k, 0)
        d = vb - va
        rlines.append(
            f"  {k}: A={va} ({_pct(va, na)})  B={vb} ({_pct(vb, nb)})  Δ={d:+}"
        )
    _print_block(f"## {asset} — counts_by_reason", rlines)

    tda = a.get("tuning_dig") or {}
    tdb = b.get("tuning_dig") or {}
    if not isinstance(tda, dict):
        tda = {}
    if not isinstance(tdb, dict):
        tdb = {}
    tlines = [
        f"  primary_skip_driver: A={tda.get('primary_skip_driver')!r}  B={tdb.get('primary_skip_driver')!r}",
        f"  up_down_ratio: A={tda.get('up_down_ratio')}  B={tdb.get('up_down_ratio')}",
    ]
    mix_a = tda.get("skip_mix_pct_of_all_bars") or {}
    mix_b = tdb.get("skip_mix_pct_of_all_bars") or {}
    if isinstance(mix_a, dict) and isinstance(mix_b, dict):
        for key in sorted(set(mix_a) | set(mix_b)):
            tlines.append(f"  skip_mix[{key}]: A={mix_a.get(key)}  B={mix_b.get(key)}")
    aa = tda.get("after_crt_no_distribution_inside_next_bar")
    ab = tdb.get("after_crt_no_distribution_inside_next_bar")
    if aa or ab:
        tlines.append(f"  after_crt_no_distribution_inside_next_bar A={aa}")
        tlines.append(f"  after_crt_no_distribution_inside_next_bar B={ab}")
    tlines.append(f"  htf_narrative A: {(tda.get('htf_narrative') or '')[:160]}")
    tlines.append(f"  htf_narrative B: {(tdb.get('htf_narrative') or '')[:160]}")
    runs_a = tda.get("suggested_ab_runs") or []
    runs_b = tdb.get("suggested_ab_runs") or []
    if isinstance(runs_a, list):
        tlines.append(f"  suggested_ab_runs A ({len(runs_a)}):")
        for r in runs_a[:6]:
            if isinstance(r, dict):
                tlines.append(f"    - {r.get('focus')}: {r.get('next_experiment', '')[:100]}")
    if isinstance(runs_b, list):
        tlines.append(f"  suggested_ab_runs B ({len(runs_b)}):")
        for r in runs_b[:6]:
            if isinstance(r, dict):
                tlines.append(f"    - {r.get('focus')}: {r.get('next_experiment', '')[:100]}")
    _print_block(f"## {asset} — tuning_dig", tlines)
    print()


def main() -> int:
    p = argparse.ArgumentParser(description="Diff two crt_signal_history lessons JSON files.")
    p.add_argument("path_a", type=Path, help="baseline lessons JSON")
    p.add_argument("path_b", type=Path, help="comparison lessons JSON")
    p.add_argument("--asset", type=str, default=None, help="only this asset (multi-asset files)")
    p.add_argument("--label-a", type=str, default="A", metavar="LABEL")
    p.add_argument("--label-b", type=str, default="B", metavar="LABEL")
    args = p.parse_args()

    if not args.path_a.is_file():
        print(f"error: not a file: {args.path_a}", file=sys.stderr)
        return 2
    if not args.path_b.is_file():
        print(f"error: not a file: {args.path_b}", file=sys.stderr)
        return 2

    ja, jb = _load(args.path_a), _load(args.path_b)
    ma, mb = _per_asset_map(ja), _per_asset_map(jb)

    print(f"# diff: {args.path_a.resolve()}\n#   vs: {args.path_b.resolve()}\n")

    if "rollup_counts" in ja and "rollup_counts" in jb:
        ra, rb = ja["rollup_counts"], jb["rollup_counts"]
        if isinstance(ra, dict) and isinstance(rb, dict):
            lines = [f"  rollup A={ra}", f"  rollup B={rb}"]
            _print_block("## rollup_counts (multi file)", lines)
            print()

    keys_a, keys_b = set(ma), set(mb)
    common = sorted(keys_a & keys_b)
    only_a = sorted(keys_a - keys_b)
    only_b = sorted(keys_b - keys_a)
    if only_a or only_b:
        print(f"# assets only in A: {only_a}  only in B: {only_b}\n")

    if args.asset:
        if args.asset not in ma or args.asset not in mb:
            print(f"error: --asset {args.asset!r} not in both files", file=sys.stderr)
            return 2
        diff_one_asset(
            label_a=args.label_a,
            label_b=args.label_b,
            a=ma[args.asset],
            b=mb[args.asset],
            asset=args.asset,
        )
        return 0

    for asset in common:
        diff_one_asset(
            label_a=args.label_a,
            label_b=args.label_b,
            a=ma[asset],
            b=mb[asset],
            asset=asset,
        )
    if not common:
        print("error: no overlapping assets to diff", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
