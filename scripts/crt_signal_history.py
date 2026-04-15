#!/usr/bin/env python3
from __future__ import annotations

"""
Rebuild **full CRT signal history** over a date range (every closed 15m bar), histogram reasons,
and write a **lessons** JSON for strategy tuning (includes ``tuning_dig``: skip drivers, A/B ideas,
persistence after distribution-SKIP, HTF narrative, top signal hours).

Important: :func:`polymarket_htf.crt_strategy.crt_signal_row` only defines **two** directional
reason strings (bull / bear AMD sweep + C3 inside). Historical mining cannot discover new
``UP``/``DOWN`` *reason labels* without changing that function; this tool still gives you the
**SKIP** mix (where to loosen gates) and bar counts (~70k bars / 2y / asset at 15m).

Examples::

  # ~2 years BTC, Binance OHLC (recommended for long spans; fewer Pyth chunk calls)
  ./.venv/bin/python scripts/crt_signal_history.py --asset btc --days 730 \\
    --price-source binance --crt-preset loose --crt-no-htf-filter \\
    --crt-sweep-conflict prefer_bull --lessons-out var/crt_lessons_btc_2y.json

  # Same, plus one JSONL row per bar (large; default off)
  ... --jsonl-out var/crt_signals_btc_2y.jsonl

  # Richer lessons (HTF quantiles by reason, hour-of-day signals, transitions) + multi-asset rollup
  ./.venv/bin/python scripts/crt_signal_history.py --assets btc eth sol --days 90 --price-source pyth \\
    --crt-preset loose --crt-no-htf-filter --crt-sweep-conflict prefer_bull \\
    --lessons-out var/crt_lessons_multi_90d.json
"""
import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_htf.crt_strategy import CRTParams


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CRT side/reason histogram + lessons JSON over a range.")
    p.add_argument("--asset", default="btc", help="single asset when --assets not set")
    p.add_argument(
        "--assets",
        nargs="+",
        default=None,
        metavar="ASSET",
        help="if set: run each asset and write one combined JSON (overrides --asset)",
    )
    p.add_argument(
        "--start",
        type=str,
        default=None,
        help="UTC range start (e.g. 2024-04-15). Default: --end minus --days",
    )
    p.add_argument(
        "--end",
        type=str,
        default=None,
        help="UTC range end exclusive (e.g. 2026-04-15). Default: now UTC",
    )
    p.add_argument("--days", type=float, default=730.0, help="if --start omitted: window length in days (default 730≈2y)")
    p.add_argument("--warmup-days", type=float, default=45.0, help="extra history before --start for CRT context")
    p.add_argument("--price-source", choices=["binance", "pyth"], default="binance")
    p.add_argument("--crt-preset", choices=["default", "loose", "loose_htf", "loose_plus"], default="loose")
    p.add_argument("--crt-no-htf-filter", action="store_true")
    p.add_argument("--crt-sweep-conflict", choices=["skip", "prefer_bull", "prefer_bear"], default="prefer_bull")
    p.add_argument("--crt-min-range-pct", type=float, default=None)
    p.add_argument("--crt-distribution-buffer-frac", type=float, default=None)
    p.add_argument(
        "--lessons-out",
        type=Path,
        default=None,
        help="write merged lessons JSON (default: var/crt_signal_lessons_<asset>_<start>_<end>.json)",
    )
    p.add_argument(
        "--jsonl-out",
        type=Path,
        default=None,
        help="optional (single --asset only): one JSON object per bar in [start,end)",
    )
    p.add_argument(
        "--no-enriched-lessons",
        action="store_true",
        help="omit HTF/hour/transition context (smaller JSON; schema_version stays 1)",
    )
    return p.parse_args()


def _run_one_asset(
    *,
    asset: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    warm: pd.Timestamp,
    price_source: str,
    params: CRTParams,
    jsonl_out: Path | None,
    no_enriched: bool,
) -> tuple[dict[str, object], dict[str, int]]:
    from polymarket_htf.assets import binance_symbol, normalize_asset
    from polymarket_htf.crt_signal_history import (
        build_lessons_payload,
        enrich_with_bar_context,
        params_to_jsonable,
        summarize_side_reason,
    )
    from polymarket_htf.crt_strategy import build_exec_frame, crt_signal_row

    a = normalize_asset(asset)
    pair = binance_symbol(a)
    print(
        f"crt_signal_history: asset={a} pair={pair} [{start} .. {end}) "
        f"price_source={price_source}",
        file=sys.stderr,
        flush=True,
    )

    df = build_exec_frame(
        binance_pair=pair,
        params=params,
        range_start=warm,
        range_end=end,
        warmup_days=0.0,
        price_source=price_source,  # type: ignore[arg-type]
    )
    if df.empty:
        raise RuntimeError(f"empty OHLC frame for {a}")
    in_range = df.loc[(df.index >= start) & (df.index < end)]
    if in_range.empty:
        raise RuntimeError(f"no rows in range for {a}")

    sides: list[str] = []
    reasons: list[str] = []
    for _, row in in_range.iterrows():
        s, r = crt_signal_row(row, params=params)
        sides.append(s)
        reasons.append(r)
    ts_list = [str(x) for x in in_range.index]

    summary = summarize_side_reason(sides, reasons, bar_timestamps=ts_list)
    bars_15m = int(summary["bars"])
    years = (end - start).total_seconds() / (86400.0 * 365.25)
    expected = (end - start).total_seconds() / 900.0
    meta = {
        "asset": a,
        "binance_pair": pair,
        "range_start_utc": str(start),
        "range_end_utc_exclusive": str(end),
        "range_years_approx": round(years, 4),
        "bars_15m_in_range": bars_15m,
        "expected_bars_15m_if_complete": round(expected, 2),
        "warmup_days_before_start": (start - warm).total_seconds() / 86400.0,
        "price_source": price_source,
        "crt_preset": getattr(params, "_preset_label", None),
        "crt_no_htf_filter": not bool(getattr(params, "use_htf_location_filter", True)),
        "crt_params_effective": params_to_jsonable(params),
    }
    enriched = None
    if not no_enriched:
        htf = in_range["htf_rp_c1"] if "htf_rp_c1" in in_range.columns else None
        rp = in_range["c1_range_pct"] if "c1_range_pct" in in_range.columns else None
        sb = in_range["sweep_below_crl"] if "sweep_below_crl" in in_range.columns else None
        sa = in_range["sweep_above_crh"] if "sweep_above_crh" in in_range.columns else None
        ins = in_range["c3_inside_c1"] if "c3_inside_c1" in in_range.columns else None
        enriched = enrich_with_bar_context(
            sides=sides,
            reasons=reasons,
            index=in_range.index,
            htf_rp_c1=htf,
            c1_range_pct=rp,
            sweep_below_crl=sb,
            sweep_above_crh=sa,
            c3_inside_c1=ins,
        )

    lessons = build_lessons_payload(meta=meta, summary=summary, enriched=enriched)

    if jsonl_out is not None:
        jsonl_out.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_out.open("w", encoding="utf-8") as jf:
            for i, idx in enumerate(in_range.index):
                row = in_range.iloc[i]
                rec = {
                    "timestamp": str(idx),
                    "asset": a,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "side": sides[i],
                    "reason": reasons[i],
                }
                for k in ("crh", "crl", "htf_rp_c1", "c1_range_pct"):
                    v = row.get(k)
                    if v is not None and pd.notna(v):
                        rec[k] = float(v)
                jf.write(json.dumps(rec) + "\n")
        print(f"wrote {jsonl_out.resolve()} lines={bars_15m}", file=sys.stderr)

    counts = {"UP": summary["counts_by_side"].get("UP", 0), "DOWN": summary["counts_by_side"].get("DOWN", 0), "SKIP": summary["counts_by_side"].get("SKIP", 0)}
    return lessons, counts


def main() -> int:
    args = _parse_args()
    from polymarket_htf.assets import normalize_asset
    from polymarket_htf.config_env import load_dotenv_files
    from polymarket_htf.crt_presets import apply_crt_preset
    load_dotenv_files(project_root=ROOT)

    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.now(tz="UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")

    if args.start:
        start = pd.Timestamp(args.start)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        else:
            start = start.tz_convert("UTC")
    else:
        start = end - pd.Timedelta(days=float(args.days))

    if start >= end:
        print("error: start must be < end", file=sys.stderr)
        return 2

    assets = [normalize_asset(x) for x in args.assets] if args.assets else [normalize_asset(args.asset)]
    if len(assets) > 1 and args.jsonl_out is not None:
        print("error: --jsonl-out is only supported with a single asset (omit --assets or pass one)", file=sys.stderr)
        return 2

    crt_kw: dict = {
        "use_htf_location_filter": not args.crt_no_htf_filter,
        "sweep_conflict_resolve": args.crt_sweep_conflict,
    }
    if args.crt_min_range_pct is not None:
        crt_kw["min_candle1_range_pct"] = float(args.crt_min_range_pct)
    if args.crt_distribution_buffer_frac is not None:
        crt_kw["distribution_inside_buffer_frac"] = float(args.crt_distribution_buffer_frac)
    params = CRTParams(**crt_kw)
    params = apply_crt_preset(params, args.crt_preset)
    if args.crt_no_htf_filter:
        params = replace(params, use_htf_location_filter=False)
    setattr(params, "_preset_label", args.crt_preset)

    warm = start - pd.Timedelta(days=float(args.warmup_days))
    print(
        f"crt_signal_history: warmup={args.warmup_days}d preset={args.crt_preset} assets={assets}",
        file=sys.stderr,
        flush=True,
    )

    per_asset: dict[str, Any] = {}
    rollup = {"bars": 0, "UP": 0, "DOWN": 0, "SKIP": 0}
    for a in assets:
        lessons_one, counts = _run_one_asset(
            asset=a,
            start=start,
            end=end,
            warm=warm,
            price_source=args.price_source,
            params=params,
            jsonl_out=args.jsonl_out if len(assets) == 1 else None,
            no_enriched=bool(args.no_enriched_lessons),
        )
        per_asset[a] = lessons_one
        rollup["bars"] += int(lessons_one["summary"]["bars"])
        for k in ("UP", "DOWN", "SKIP"):
            rollup[k] += counts[k]

    if len(assets) == 1:
        lessons = per_asset[assets[0]]
        lessons["meta"]["generated_at"] = datetime.now(timezone.utc).isoformat()
    else:
        lessons = {
            "schema_version": 2,
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "assets": assets,
                "range_start_utc": str(start),
                "range_end_utc_exclusive": str(end),
                "warmup_days_before_start": float(args.warmup_days),
                "price_source": args.price_source,
                "crt_preset": args.crt_preset,
                "crt_no_htf_filter": bool(args.crt_no_htf_filter),
            },
            "rollup_counts": rollup,
            "per_asset": per_asset,
        }

    out_path = args.lessons_out
    if out_path is None:
        tag_s = start.strftime("%Y%m%d")
        tag_e = (end - pd.Timedelta(seconds=1)).strftime("%Y%m%d")
        if len(assets) == 1:
            out_path = Path("var") / f"crt_signal_lessons_{assets[0]}_{tag_s}_{tag_e}.json"
        else:
            out_path = Path("var") / f"crt_signal_lessons_multi_{tag_s}_{tag_e}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(lessons, indent=2), encoding="utf-8")
    print(f"wrote {out_path.resolve()}", file=sys.stderr)

    print(
        json.dumps(
            {
                "assets": assets,
                "rollup": rollup,
                "lessons_path": str(out_path.resolve()),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
