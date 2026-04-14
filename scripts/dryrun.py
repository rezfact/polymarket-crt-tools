#!/usr/bin/env python3
"""
Poll Gamma + OHLC (Binance or Pyth), log **would-be** trades (no keys, no orders).

Use for timestamped notes: slug, CRT side, reason, optional Gamma headline.

Primary journal: ``--journal`` (default ``var/journal.jsonl`` — repo-relative ``var/``, not Linux ``/var``).
Optional unified eval copy: set env ``STRATEGY_EVAL_JOURNAL`` / ``LIVE_EVAL_JOURNAL`` (e.g. absolute path on VPS).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_htf._venv_reexec import reexec_if_needed, using_project_venv


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tf", type=int, default=15, choices=[5, 15])
    p.add_argument("--interval-sec", type=float, default=45.0, help="sleep between cycles")
    p.add_argument("--journal", type=Path, default=Path("var/journal.jsonl"))
    p.add_argument("--once", action="store_true", help="single poll then exit")
    p.add_argument(
        "--price-source",
        choices=["binance", "pyth"],
        default="pyth",
        help="CRT candles: Pyth Benchmarks TV (default) vs Binance REST",
    )
    p.add_argument(
        "--log-on-bar-change",
        action="store_true",
        help="only log when the **last closed** exec bar changes (uses completed bar; ~4 lines/hour/asset at 15m)",
    )
    p.add_argument(
        "--state-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="with --log-on-bar-change: JSON dict asset→last bar timestamp (persist across runs)",
    )
    p.add_argument(
        "--crt-no-htf-filter",
        action="store_true",
        help="CRT: do not require Candle-1 close in HTF discount/premium band",
    )
    p.add_argument("--crt-htf-discount-max", type=float, default=None, help="CRT: bull zone upper bound on HTF_rp (default 0.42)")
    p.add_argument("--crt-htf-premium-min", type=float, default=None, help="CRT: bear zone lower bound on HTF_rp (default 0.58)")
    p.add_argument(
        "--crt-min-range-pct",
        type=float,
        default=None,
        help="CRT: min Candle-1 range %% of mid (default 0.0002); lower → fewer c1_range_too_tight",
    )
    p.add_argument(
        "--crt-sweep-conflict",
        choices=["skip", "prefer_bull", "prefer_bear"],
        default="skip",
        help="CRT: when Candle-2 sweeps both CRH and CRL (default skip); prefer_* breaks tie for looser signals",
    )
    p.add_argument(
        "--crt-distribution-buffer-frac",
        type=float,
        default=None,
        metavar="FRAC",
        help="CRT: widen C3 'inside C1' by FRAC*(CRH-CRL) on each side (0=strict; try 0.005–0.02)",
    )
    p.add_argument(
        "--crt-preset",
        choices=["default", "loose", "loose_htf", "loose_plus"],
        default="default",
        help="CRT bundle to cut SKIPs: loose=no HTF + prefer_bull conflicts + distribution buffer; "
        "loose_htf=wider HTF bands + buffer; loose_plus=wider C3 buffer (see polymarket_htf.crt_presets)",
    )
    p.add_argument(
        "--gamma-min-side-price",
        type=float,
        default=None,
        metavar="P",
        help="when set with UP/DOWN: log gamma_side_gate; UP checks Yes mid, DOWN checks No mid >= P",
    )
    p.add_argument(
        "--gamma-max-side-price",
        type=float,
        default=None,
        metavar="P",
        help="when set with UP/DOWN: require entry mid <= P (filters lottery-ticket cheap sides)",
    )
    args = p.parse_args()

    from polymarket_htf.config_env import load_dotenv_files

    load_dotenv_files(project_root=ROOT)

    if args.log_on_bar_change:
        print(
            "dryrun: logging CRT on **last closed** 15m bar only. "
            "For arm/prearm/paper_fill (sweet-spot **waiting**), run: "
            "scripts/watch_sweet_spot.py",
            file=sys.stderr,
        )

    try:
        from polymarket_htf.crt_presets import apply_crt_preset
        from polymarket_htf.crt_strategy import CRTParams, last_signal_completed_bar, last_signal_for_asset
        from polymarket_htf.gamma import fetch_event_by_slug, gamma_market_headline, gamma_side_price_gate, scan_all_assets
        from polymarket_htf.journal import append_jsonl_with_eval_mirror, utc_now_iso
        from polymarket_htf.assets import supported_assets
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

    def _sleep_after_error() -> None:
        time.sleep(min(max(5.0, float(args.interval_sec) / 4.0), 60.0))

    crt_kw: dict = {
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
    params = CRTParams(**crt_kw)
    params = apply_crt_preset(params, args.crt_preset)
    if args.crt_no_htf_filter:
        params = replace(params, use_htf_location_filter=False)
    last_bar_ts: dict[str, str | None] = {}
    if args.log_on_bar_change and args.state_file is not None and args.state_file.is_file():
        try:
            raw = json.loads(args.state_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                last_bar_ts = {str(k): str(v) for k, v in raw.items() if v is not None}
        except (json.JSONDecodeError, OSError):
            last_bar_ts = {}

    def _save_state() -> None:
        if args.log_on_bar_change and args.state_file is not None:
            args.state_file.parent.mkdir(parents=True, exist_ok=True)
            args.state_file.write_text(json.dumps(last_bar_ts, indent=0), encoding="utf-8")

    while True:
        try:
            slugs = scan_all_assets(tf_minutes=args.tf, require_active=True, neighbor_windows=6)
            for asset in supported_assets():
                slug = slugs.get(asset)
                if args.log_on_bar_change:
                    sig = last_signal_completed_bar(asset, params=params, price_source=args.price_source)
                    tsb = sig.get("timestamp")
                    if tsb is None:
                        continue
                    if last_bar_ts.get(asset) == str(tsb):
                        continue
                    last_bar_ts[asset] = str(tsb)
                else:
                    sig = last_signal_for_asset(asset, params=params, price_source=args.price_source)
                ev = fetch_event_by_slug(slug) if slug else None
                rec = {
                    "kind": "dryrun",
                    "ts": utc_now_iso(),
                    "asset": asset,
                    "slug": slug,
                    "gamma": gamma_market_headline(ev) if ev else None,
                    "signal": sig,
                }
                if (
                    ev is not None
                    and str(sig.get("side", "SKIP")) in ("UP", "DOWN")
                    and (args.gamma_min_side_price is not None or args.gamma_max_side_price is not None)
                ):
                    ok, det = gamma_side_price_gate(
                        ev,
                        side=str(sig["side"]),
                        min_side_price=args.gamma_min_side_price,
                        max_side_price=args.gamma_max_side_price,
                    )
                    rec["gamma_side_gate"] = {"pass": ok, **det}
                append_jsonl_with_eval_mirror(args.journal, rec, pipeline="dryrun")
                print(rec["ts"], asset, slug, sig.get("side"), sig.get("reason"))
                if args.log_on_bar_change:
                    _save_state()
        except Exception as e:  # noqa: BLE001 — keep long-lived dryrun alive
            msg = f"{utc_now_iso()} dryrun_cycle_error {type(e).__name__}: {e}"
            print(msg, file=sys.stderr)
            if args.once:
                return 1
            _sleep_after_error()
            continue
        if args.once:
            break
        time.sleep(args.interval_sec)
    return 0


if __name__ == "__main__":
    reexec_if_needed(root=ROOT, script=Path(__file__).resolve())
    raise SystemExit(main())
