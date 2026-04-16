#!/usr/bin/env python3
"""Summarize WSS near-miss vs paper_fill.

- **watch** (default when JSONL contains ``wss_diag``): live ``watch_sweet_spot`` — first/last diag
  per slug for timeout windows (``retrace_frac`` path, or legacy fib distance fields if present).
- **wss_sim**: output of ``scripts/month_crt_wss.py --wss-nearmiss`` — one row per window with ``nm_*``.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict


def edge_dist_legacy(d: dict) -> float:
    """Old ``wss_diag`` rows with fib distances (pre–no-fib watcher)."""
    if d.get("in_fib"):
        return 0.0
    lo = float(d.get("dist_below_fib_lo") or 0)
    hi = float(d.get("dist_above_fib_hi") or 0)
    if lo > 0 and hi > 0:
        return min(lo, hi)
    return lo if lo > 0 else hi


def _percentile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    r = (len(xs) - 1) * (p / 100.0)
    lo = int(math.floor(r))
    hi = int(math.ceil(r))
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - r) + xs[hi] * (r - lo)


def _flt(x: object) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _diag_series_legacy(ds: list[dict]) -> bool:
    return any("in_fib" in x or "dist_below_fib_lo" in x for x in ds)


def summarize_watch(rows: list[dict]) -> int:
    by_slug: dict[str, list[dict]] = defaultdict(list)
    fills: set[str] = set()
    timeouts: list[str] = []
    for r in rows:
        slug = r.get("slug")
        if not slug:
            continue
        slug = str(slug)
        k = r.get("kind")
        if k == "wss_diag":
            by_slug[slug].append(r)
        elif k == "paper_fill":
            fills.add(slug)
        elif k == "skip" and r.get("reason") == "timeout":
            timeouts.append(slug)

    with_diag = [s for s in sorted(set(timeouts)) if s not in fills and by_slug.get(s)]
    print(
        "rows",
        len(rows),
        "paper_fill",
        len(fills),
        "timeout_slugs",
        len(set(timeouts)),
        "timeouts_with_wss_diag",
        len(with_diag),
    )
    print()
    for slug in with_diag:
        ds = sorted(by_slug[slug], key=lambda x: float(x.get("now") or 0))
        a, z = ds[0], ds[-1]
        sd = a.get("side")
        print(slug, "side=", sd, "n_diag=", len(ds))
        if _diag_series_legacy(ds):
            ever_in = sum(1 for x in ds if x.get("in_fib"))
            min_e = min(edge_dist_legacy(x) for x in ds)
            with_pull = [edge_dist_legacy(x) for x in ds if x.get("pullback_ok")]
            min_e_pull = min(with_pull) if with_pull else None
            print(
                "  (legacy fib diag) FIRST edge=%.1f pull=%s entry=%s in_fib=%s"
                % (
                    edge_dist_legacy(a),
                    a.get("pullback_ok"),
                    a.get("entry_window_ok"),
                    a.get("in_fib"),
                )
            )
            print(
                "  LAST  edge=%.1f pull=%s entry=%s in_fib=%s secs_left=%.0f"
                % (
                    edge_dist_legacy(z),
                    z.get("pullback_ok"),
                    z.get("entry_window_ok"),
                    z.get("in_fib"),
                    float(z.get("secs_to_T_end") or 0),
                )
            )
            print(
                "  ever_in_fib_diags=%d min_edge=%.1f min_edge_when_pullback_ok=%s"
                % (ever_in, min_e, f"{min_e_pull:.1f}" if min_e_pull is not None else "n/a")
            )
        else:
            retr = [float(x.get("retrace_frac") or 0) for x in ds]
            print(
                "  FIRST retrace_frac=%.6f pull=%s entry=%s late=%s since_T=%.0f"
                % (
                    float(a.get("retrace_frac") or 0),
                    a.get("pullback_ok"),
                    a.get("entry_window_ok"),
                    a.get("late_fill_ok"),
                    float(a.get("secs_since_T") or 0),
                )
            )
            print(
                "  LAST  retrace_frac=%.6f pull=%s entry=%s late=%s secs_left=%.0f since_T=%.0f"
                % (
                    float(z.get("retrace_frac") or 0),
                    z.get("pullback_ok"),
                    z.get("entry_window_ok"),
                    z.get("late_fill_ok"),
                    float(z.get("secs_to_T_end") or 0),
                    float(z.get("secs_since_T") or 0),
                )
            )
            print("  max_retrace_frac=%.6f (session vs spot; UP from hi, DOWN from lo)" % max(retr))
        print()
    return 0


def summarize_wss_sim(rows: list[dict]) -> int:
    sim = [r for r in rows if r.get("kind") == "wss_sim"]
    if not sim:
        print("no wss_sim rows", file=sys.stderr)
        return 1
    has_nm = any("nm_max_retrace_frac" in r or "nm_ever_pullback_ok" in r for r in sim)
    if not has_nm:
        print(
            "wss_sim rows have no nm_* fields; re-run with: "
            "scripts/month_crt_wss.py ... --wss-nearmiss",
            file=sys.stderr,
        )
        return 1

    by_res: dict[str, list[dict]] = defaultdict(list)
    for r in sim:
        by_res[str(r.get("result") or "")].append(r)

    def block(label: str, rs: list[dict]) -> None:
        if not rs:
            print(f"{label}: (none)")
            print()
            return
        n = len(rs)
        ever_pull = sum(1 for x in rs if x.get("nm_ever_pullback_ok"))
        last_no_entry = sum(1 for x in rs if x.get("nm_last_entry_window_ok") is False)
        last_pull = sum(1 for x in rs if x.get("nm_last_pullback_ok"))
        mxr = [float(x["nm_max_retrace_frac"]) for x in rs if x.get("nm_max_retrace_frac") is not None]
        print(f"{label}: n={n}")
        print(f"  nm_ever_pullback_ok: {ever_pull} ({100.0 * ever_pull / n:.1f}%)")
        print(f"  nm_last_entry_window_ok==false: {last_no_entry} ({100.0 * last_no_entry / n:.1f}%)")
        print(f"  nm_last_pullback_ok==true: {last_pull} ({100.0 * last_pull / n:.1f}%)")
        if mxr:
            print(
                "  nm_max_retrace_frac: min=%.6f p50=%s p90=%s max=%.6f"
                % (
                    min(mxr),
                    f"{_percentile(mxr, 50):.6f}" if _percentile(mxr, 50) is not None else "n/a",
                    f"{_percentile(mxr, 90):.6f}" if _percentile(mxr, 90) is not None else "n/a",
                    max(mxr),
                )
            )
        print()

    print("source=wss_sim (month_crt_wss --wss-nearmiss)")
    print("rows", len(rows), "wss_sim", len(sim))
    print()
    for key in ("timeout", "paper_fill", "skip", "no_spot_data"):
        if key in by_res:
            block(f"result={key}", by_res[key])
    other = [k for k in by_res if k not in ("timeout", "paper_fill", "skip", "no_spot_data")]
    for k in sorted(other):
        block(f"result={k}", by_res[k])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=str, nargs="?", default="-", help="JSONL path or - for stdin")
    ap.add_argument(
        "--mode",
        choices=("auto", "watch", "wss_sim"),
        default="auto",
        help="auto: use wss_diag stream if present, else wss_sim batch",
    )
    args = ap.parse_args()
    if args.path == "-":
        raw = sys.stdin.read()
    else:
        raw = open(args.path, encoding="utf-8").read()

    rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
    mode = args.mode
    if mode == "auto":
        has_diag = any(r.get("kind") == "wss_diag" for r in rows)
        has_sim = any(r.get("kind") == "wss_sim" for r in rows)
        if has_diag:
            mode = "watch"
        elif has_sim:
            mode = "wss_sim"
        else:
            print("no wss_diag or wss_sim rows; pass --mode explicitly if format differs", file=sys.stderr)
            return 1

    if mode == "watch":
        return summarize_watch(rows)
    return summarize_wss_sim(rows)


if __name__ == "__main__":
    raise SystemExit(main())
