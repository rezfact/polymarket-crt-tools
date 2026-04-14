#!/usr/bin/env python3
"""
Paper **sweet-spot monitor** (C3 arm, O3 Chainlink, E3/E5/E6, S3 revoke) — no orders.

CRT OHLC defaults to **Pyth** (``--price-source pyth``), same as ``dryrun.py``, to avoid macOS
OpenSSL issues with Binance. On startup it **re-execs** into the repo venv when ``sys.prefix`` is not
``.venv313`` / ``.venv`` (even if ``python`` is the same Homebrew binary — venv is detected via ``pyvenv.cfg``).
Candidates: ``POLYMARKET_HTF_PYTHON`` (must be a venv), ``.venv313/bin/python``, ``.venv/bin/python``.
Disable with ``POLYMARKET_HTF_NO_VENV_REEXEC=1``.

Logs JSONL events; tune flags to benchmark vs a simpler baseline (e.g. ``--entry-mode``).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_htf._venv_reexec import reexec_if_needed, using_project_venv


def main() -> int:
    p = argparse.ArgumentParser(description="Paper sweet-spot watcher (see polymarket_htf.watch_session).")
    p.add_argument("--asset", default="btc")
    p.add_argument("--tf", type=int, default=15, choices=[5, 15])
    p.add_argument("--interval-sec", type=float, default=5.0)
    p.add_argument("--journal", type=Path, default=Path("var/watch_sweet_spot.jsonl"))
    p.add_argument("--once", action="store_true")
    p.add_argument(
        "--price-source",
        choices=["binance", "pyth"],
        default="pyth",
        help="CRT candle source (default pyth: matches dryrun; use binance if your CA bundle works)",
    )

    p.add_argument("--prearm-sec", type=float, default=12.0)
    p.add_argument("--no-prearm", action="store_true")
    p.add_argument("--slug-offset-steps", type=int, default=1)

    p.add_argument(
        "--entry-mode",
        choices=["until_buffer", "first_minutes"],
        default="until_buffer",
        help="until_buffer: any time from T until T_end-buffer; first_minutes: only first N minutes",
    )
    p.add_argument("--entry-end-buffer-sec", type=float, default=90.0)
    p.add_argument("--entry-first-minutes", type=float, default=8.0)

    p.add_argument("--max-gamma-outcome-dev", type=float, default=0.12)
    p.add_argument("--allow-gamma-inactive", action="store_true")

    p.add_argument("--pullback-frac", type=float, default=0.0008)
    p.add_argument("--fib-lo", type=float, default=0.618)
    p.add_argument("--fib-hi", type=float, default=0.786)
    p.add_argument("--chainlink-stale-sec", type=float, default=150.0)

    p.add_argument("--no-signal-revoke", action="store_true", help="disable S3 (same as full revoke off)")
    p.add_argument(
        "--sticky-arm",
        action="store_true",
        help="priority-1 paper mode: do not cancel arm when CRT flips on the next bar; "
        "hold armed side until paper_fill or timeout (S3 off for that window)",
    )

    p.add_argument("--crt-no-htf-filter", action="store_true")
    p.add_argument("--crt-htf-discount-max", type=float, default=None)
    p.add_argument("--crt-htf-premium-min", type=float, default=None)
    p.add_argument("--crt-min-range-pct", type=float, default=None)
    p.add_argument(
        "--crt-sweep-conflict",
        choices=["skip", "prefer_bull", "prefer_bear"],
        default="skip",
    )
    p.add_argument(
        "--crt-distribution-buffer-frac",
        type=float,
        default=None,
        metavar="FRAC",
        help="CRT: widen C3 inside-C1 by FRAC*(CRH-CRL) each side (default strict 0)",
    )
    p.add_argument(
        "--crt-preset",
        choices=["default", "loose", "loose_htf", "loose_plus"],
        default="default",
        help="CRT bundle to cut SKIPs (see polymarket_htf.crt_presets)",
    )
    p.add_argument(
        "--gamma-min-side-price",
        type=float,
        default=None,
        metavar="P",
        help="skip arm unless Gamma entry mid for CRT side is in [P, --gamma-max-side-price]",
    )
    p.add_argument(
        "--gamma-max-side-price",
        type=float,
        default=None,
        metavar="P",
        help="skip arm when entry mid > P (e.g. 0.88 to avoid paying 0.93 for DOWN)",
    )
    args = p.parse_args()

    if args.tf != 15:
        print("error: CRT defaults are 15m exec; use tf=15 unless you extend CRTParams", file=sys.stderr)
        return 2

    try:
        from polymarket_htf.crt_presets import apply_crt_preset
        from polymarket_htf.crt_strategy import CRTParams
        from polymarket_htf.journal import append_jsonl, utc_now_iso
        from polymarket_htf.watch_session import SweetSpotWatchParams, SweetSpotWatchSession
    except ModuleNotFoundError as e:
        req = ROOT / "requirements.txt"
        if using_project_venv(ROOT):
            fix = f"  Fix: {sys.executable} -m pip install -r {req}"
        else:
            fix = (
                f"  You are not using the repo venv (sys.prefix={sys.prefix!s}).\n"
                f"  Fix: cd {ROOT} && python3.13 -m venv .venv313 && "
                f".venv313/bin/python -m pip install -r {req}\n"
                f"  Then run: {ROOT / '.venv313' / 'bin' / 'python'} {Path(__file__).resolve()} …"
            )
        print(
            f"error: missing Python package ({e!s}).\n"
            f"  Interpreter: {sys.executable}\n"
            f"{fix}",
            file=sys.stderr,
        )
        return 2

    crt_kw: dict = {
        "exec_interval": "15m",
        "context_interval": "1h",
        "use_htf_location_filter": not args.crt_no_htf_filter,
        "sweep_conflict_resolve": args.crt_sweep_conflict,
    }
    if args.crt_htf_discount_max is not None:
        crt_kw["htf_discount_max"] = float(args.crt_htf_discount_max)
    if args.crt_htf_premium_min is not None:
        crt_kw["htf_premium_min"] = float(args.crt_htf_premium_min)
    if args.crt_min_range_pct is not None:
        crt_kw["min_candle1_range_pct"] = float(args.crt_min_range_pct)
    if args.crt_distribution_buffer_frac is not None:
        crt_kw["distribution_inside_buffer_frac"] = float(args.crt_distribution_buffer_frac)
    crt = CRTParams(**crt_kw)
    crt = apply_crt_preset(crt, args.crt_preset)
    if args.crt_no_htf_filter:
        crt = replace(crt, use_htf_location_filter=False)
    prm = SweetSpotWatchParams(
        asset=args.asset,
        tf_minutes=args.tf,
        price_source=args.price_source,
        crt=crt,
        use_prearm=not args.no_prearm,
        prearm_sec=args.prearm_sec,
        slug_offset_steps=args.slug_offset_steps,
        entry_mode=args.entry_mode,
        entry_end_buffer_sec=args.entry_end_buffer_sec,
        entry_first_minutes=args.entry_first_minutes,
        max_gamma_outcome_deviation=args.max_gamma_outcome_dev,
        require_gamma_active=not args.allow_gamma_inactive,
        gamma_min_side_price=args.gamma_min_side_price,
        gamma_max_side_price=args.gamma_max_side_price,
        pullback_frac=args.pullback_frac,
        fib_lo=args.fib_lo,
        fib_hi=args.fib_hi,
        chainlink_stale_sec=args.chainlink_stale_sec,
        enable_signal_revoke=not args.no_signal_revoke,
        sticky_arm=bool(args.sticky_arm),
    )
    sess = SweetSpotWatchSession(prm)

    while True:
        evs = sess.tick()
        for e in evs:
            row = {"ts": utc_now_iso(), **e}
            append_jsonl(args.journal, row)
            print(json.dumps(row, default=str))
        if args.once:
            break
        import time

        time.sleep(args.interval_sec)
    return 0


if __name__ == "__main__":
    reexec_if_needed(root=ROOT, script=Path(__file__).resolve())
    raise SystemExit(main())
