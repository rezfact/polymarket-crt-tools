#!/usr/bin/env python3
"""
**Fast month batch** (vs live ``dryrun`` polling): build CRT on historical OHLC, optionally export
every 15m bar, then **simulate WSS-style** fills using batched **Binance 1m** closes as a Chainlink
spot proxy inside each Polymarket ``[T, T_end)`` window.

Example (all of January 2026 UTC, ~2976 bars ≈ 96/day):

  ./scripts/month_crt_wss.py --asset btc --start 2026-01-01 --end 2026-02-01 \\
    --crt-bars-out var/crt_bars_2026-01.jsonl --wss-out var/wss_sim_2026-01.jsonl

**90d signal + WSS** (same script; use ``--end`` exclusive, e.g. 90 calendar days):

  ./scripts/month_crt_wss.py --asset btc --start 2026-01-01 --end 2026-04-01 \\
    --wss-spot-source binance_1m --wss-preset continuation \\
    --crt-bars-out var/crt_90d.jsonl --wss-out var/wss_90d.jsonl

Printed **WSS WR / PnL** uses flat stake + share mids (same knobs as toy CRT). Settlement is a
**research proxy**: first vs last close in each Polymarket window slice (not on-chain Chainlink).
Re-summarize: ``./scripts/analyze_crt_exports.py var/crt_90d.jsonl --wss var/wss_90d.jsonl``.

Notes:

- **96/day** = ``24 * 60 / 15`` fifteen-minute bars per asset (UTC calendar bars from the feed).
- WSS sim ignores **S3 revoke** (sticky-style month run). Set ``--fetch-gamma`` to hit Gamma per
  window (slow); default skips Gamma (research mode).
- Live ``watch_sweet_spot`` uses **on-chain Chainlink** for BTC; this sim uses **1m close** proxy
  for the same symbol as CRT (BTC/ETH/SOL USDT pair).

- If you see ``SSLCertVerificationError`` from Binance, install/use **certifi** (repo venv does), or
  pass ``--insecure-tls`` once to confirm the pipeline (not for production).

**Fewer CRT SKIPs:** ``--crt-preset loose`` (or ``loose_plus`` for a wider C3-inside-C1 band, or
``loose_htf`` if you want HTF on with widened bands). Optional: ``--crt-distribution-buffer-frac``.

**More meaningful WSS sim:** prefer ``--wss-spot-source binance_1m`` when Binance is reachable.
With ``crt_15m``, expect mostly ``timeout`` unless you add ``--wss-preset coarse_spot`` (aggressive,
**research only**) or ``continuation`` (aligned with live ``watch_sweet_spot --wss-preset continuation``).
Proper 1m spot remains ``--wss-spot-source binance_1m`` when reachable.

**VPS / ``.env``:** load ``.env`` from the repo root (``python-dotenv``). Defaults for this script
use the ``CRT_MONTH_*`` variables — see ``.env.example``. CLI flags override ``.env``.
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
import os as _os

from polymarket_htf.config_env import env_bool
from polymarket_htf.repo_bootstrap import ensure_repo_on_path_and_load_dotenv

ensure_repo_on_path_and_load_dotenv(ROOT)
if env_bool("CRT_MONTH_INSECURE_TLS"):
    _os.environ["REQUESTS_VERIFY"] = "0"

# Optional: disable TLS verify for broken/sandbox trust stores (must appear on argv before imports).
if "--insecure-tls" in sys.argv:
    _os.environ["REQUESTS_VERIFY"] = "0"

# Binance (and other HTTPS) need a CA bundle; some macOS/Homebrew Pythons ship a broken store.
if _os.environ.get("REQUESTS_VERIFY", "").strip().lower() not in {"0", "false", "no"}:
    try:
        import certifi as _certifi

        _bundle = _certifi.where()
        _os.environ["SSL_CERT_FILE"] = _bundle
        _os.environ["REQUESTS_CA_BUNDLE"] = _bundle
    except ImportError:
        pass

from polymarket_htf._venv_reexec import reexec_if_needed, using_project_venv


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


def _print_toy_crt_table(
    metrics: dict[str, float | int | None],
    *,
    yes_mid: float,
    fee_bps: float,
    range_s: str,
    range_e: str,
    exec_interval: str,
) -> None:
    """Markdown-style table (readable in plain text): toy next-bar WR / PnL."""
    print("", flush=True)
    print(
        f"toy CRT — next {exec_interval} bar close vs signal bar open "
        f"(not Polymarket / Chainlink); UTC {range_s} .. {range_e}",
        flush=True,
    )
    print(
        f"  flat stake=${float(metrics['stake_usd']):.2f}/trade  yes_mid={yes_mid:.3f}  "
        f"fee_roundtrip_bps={fee_bps:.1f}",
        flush=True,
    )
    trades = int(metrics["trades"])
    if trades == 0:
        print("  (no trades: no UP/DOWN in range with a following bar in the series)", flush=True)
        return
    wr = metrics["win_rate"]
    assert wr is not None
    w = int(metrics["wins"])
    ell = int(metrics["losses"])
    pg = float(metrics["pnl_gross_usd"])
    fe = float(metrics["fees_usd"])
    pn = float(metrics["pnl_net_usd"])
    print("| trades | wins | losses | win_rate | pnl_gross_usd | fees_usd | pnl_net_usd |", flush=True)
    print("|-------:|-----:|-------:|---------:|--------------:|---------:|------------:|", flush=True)
    print(
        f"| {trades} | {w} | {ell} | {wr * 100:.2f}% | {pg:.2f} | {fe:.2f} | {pn:.2f} |",
        flush=True,
    )


def main() -> int:
    from polymarket_htf.crt_month_env import month_crt_wss_arg_defaults

    d = month_crt_wss_arg_defaults()
    p = argparse.ArgumentParser(description="Month CRT export + WSS entry simulation (batch).")
    p.add_argument("--asset", default=d["asset"], help="btc | eth | sol (env: CRT_MONTH_ASSET)")
    p.add_argument(
        "--start",
        default=d["start"],
        help="UTC range start inclusive (env: CRT_MONTH_START)",
    )
    p.add_argument(
        "--end",
        default=d["end"],
        help="UTC range end **exclusive** (env: CRT_MONTH_END)",
    )
    p.add_argument(
        "--price-source",
        choices=["binance", "pyth"],
        default=d["price_source"],
        help="CRT OHLC source (env: CRT_MONTH_PRICE_SOURCE)",
    )
    p.add_argument(
        "--spot-vision",
        action=argparse.BooleanOptionalAction,
        default=d["spot_vision"],
        help="CRT OHLC from Binance Vision zips (env: CRT_MONTH_SPOT_VISION)",
    )
    p.add_argument("--vision-cache-dir", type=Path, default=d["vision_cache_dir"])
    p.add_argument("--vision-origin", type=str, default=d["vision_origin"])
    p.add_argument("--warmup-days", type=float, default=d["warmup_days"])
    p.add_argument("--exec-interval", default=d["exec_interval"], choices=["5m", "15m"])
    p.add_argument("--context-interval", default=d["context_interval"], choices=["15m", "30m", "1h", "4h"])
    p.add_argument("--range-lookback", type=int, default=d["range_lookback"])
    p.add_argument(
        "--crt-no-htf-filter",
        action=argparse.BooleanOptionalAction,
        default=d["crt_no_htf_filter"],
        help="CRT: skip HTF location filter (env: CRT_MONTH_CRT_NO_HTF_FILTER)",
    )
    p.add_argument("--crt-htf-discount-max", type=float, default=d["crt_htf_discount_max"])
    p.add_argument("--crt-htf-premium-min", type=float, default=d["crt_htf_premium_min"])
    p.add_argument("--crt-min-range-pct", type=float, default=d["crt_min_range_pct"])
    p.add_argument(
        "--crt-sweep-conflict",
        choices=["skip", "prefer_bull", "prefer_bear"],
        default=d["crt_sweep_conflict"],
    )
    p.add_argument("--crt-distribution-buffer-frac", type=float, default=d["crt_distribution_buffer_frac"])
    p.add_argument(
        "--crt-preset",
        choices=["default", "loose", "loose_htf", "loose_plus"],
        default=d["crt_preset"],
        help="CRT bundle to cut SKIPs (see polymarket_htf.crt_presets; env: CRT_MONTH_CRT_PRESET)",
    )
    p.add_argument("--crt-bars-out", type=Path, default=d["crt_bars_out"], metavar="PATH", help="write all CRT bars in range as JSONL")
    p.add_argument(
        "--wss-out",
        type=Path,
        default=d["wss_out"],
        metavar="PATH",
        help="write WSS sim rows JSONL (env: CRT_MONTH_WSS_OUT)",
    )
    p.add_argument(
        "--skip-wss",
        action=argparse.BooleanOptionalAction,
        default=d["skip_wss"],
        help="only CRT export / stats (env: CRT_MONTH_SKIP_WSS)",
    )
    p.add_argument(
        "--wss-spot-source",
        choices=["binance_1m", "crt_15m"],
        default=d["wss_spot_source"],
        help="spot path for WSS sim (env: CRT_MONTH_WSS_SPOT_SOURCE)",
    )
    p.add_argument(
        "--wss-preset",
        choices=["default", "coarse_spot", "continuation"],
        default=d["wss_preset"],
        help="WSS month preset (env: CRT_MONTH_WSS_PRESET)",
    )
    p.add_argument(
        "--fetch-gamma",
        action=argparse.BooleanOptionalAction,
        default=d["fetch_gamma"],
        help="WSS: live Gamma checks per window (env: CRT_MONTH_FETCH_GAMMA)",
    )
    p.add_argument("--slug-offset-steps", type=int, default=d["slug_offset_steps"])
    p.add_argument("--entry-mode", choices=["until_buffer", "first_minutes"], default=d["entry_mode"])
    p.add_argument("--entry-end-buffer-sec", type=float, default=d["entry_end_buffer_sec"])
    p.add_argument("--entry-first-minutes", type=float, default=d["entry_first_minutes"])
    p.add_argument("--max-gamma-outcome-dev", type=float, default=d["max_gamma_outcome_dev"])
    p.add_argument("--pullback-frac", type=float, default=d["pullback_frac"])
    p.add_argument("--fib-lo", type=float, default=d["fib_lo"])
    p.add_argument("--fib-hi", type=float, default=d["fib_hi"])
    p.add_argument(
        "--toy-stake-usd",
        type=float,
        default=d["toy_stake_usd"],
        metavar="USD",
        help="printed toy summary: flat USDC per signal (env: CRT_MONTH_TOY_STAKE_USD)",
    )
    p.add_argument(
        "--toy-yes-mid",
        type=float,
        default=d["toy_yes_mid"],
        metavar="P",
        help="printed toy summary: YES entry mid (env: CRT_MONTH_TOY_YES_MID)",
    )
    p.add_argument(
        "--toy-no-mid",
        type=float,
        default=d["toy_no_mid"],
        metavar="P",
        help="printed toy summary: explicit NO mid for DOWN (env: CRT_MONTH_TOY_NO_MID)",
    )
    p.add_argument(
        "--toy-fee-roundtrip-bps",
        type=float,
        default=d["toy_fee_roundtrip_bps"],
        metavar="BPS",
        help="printed toy summary: fee bps of stake (env: CRT_MONTH_TOY_FEE_ROUNDTRIP_BPS)",
    )
    p.add_argument(
        "--insecure-tls",
        action="store_true",
        help="set REQUESTS_VERIFY=0 for this run (fixes some SSL failures; unsafe on untrusted networks)",
    )
    args = p.parse_args()

    if not args.start or not args.end:
        print(
            "error: need --start and --end (or set CRT_MONTH_START and CRT_MONTH_END in the environment / .env)",
            file=sys.stderr,
        )
        return 2

    if args.spot_vision and args.price_source == "pyth":
        print("error: --spot-vision cannot be used with --price-source pyth", file=sys.stderr)
        return 2
    if not args.skip_wss and args.exec_interval != "15m":
        print("error: WSS sim currently supports 15m windows only; use --exec-interval 15m", file=sys.stderr)
        return 2
    if args.crt_bars_out is None and args.skip_wss:
        print("warn: nothing to write (use --crt-bars-out and/or omit --skip-wss)", file=sys.stderr)

    try:
        import pandas as pd

        from polymarket_htf.config_env import ensure_certifi_ssl_env

        ensure_certifi_ssl_env()

        from polymarket_htf.crt_presets import apply_crt_preset
        from polymarket_htf.crt_strategy import CRTParams
        from polymarket_htf.wss_month_presets import apply_wss_month_preset
        from polymarket_htf.crt_wss_monthly import (
            WssMonthSimParams,
            attach_signals_to_frame,
            build_crt_frame_for_range,
            crt_bars_to_records,
            prefetch_binance_1m_range,
            simulate_wss_for_crt_frame,
        )
        from polymarket_htf.assets import binance_symbol, normalize_asset
        from polymarket_htf.backtest_crt import summarize_toy_crt_trades, summarize_wss_sim_fills
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
        "exec_interval": args.exec_interval,  # type: ignore[arg-type]
        "context_interval": args.context_interval,  # type: ignore[arg-type]
        "range_lookback": int(args.range_lookback),
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

    print(
        f"CRT load: asset={args.asset} {args.start}..{args.end} UTC "
        f"price={args.price_source}{' vision' if args.spot_vision else ''}"
        f"{' tls=insecure' if args.insecure_tls else ''} …",
        flush=True,
    )
    try:
        df0 = build_crt_frame_for_range(
            args.asset,
            params=params,
            range_start=args.start,
            range_end=args.end,
            warmup_days=args.warmup_days,
            use_binance_vision=args.spot_vision,
            vision_cache_dir=args.vision_cache_dir,
            vision_origin=args.vision_origin,
            price_source=args.price_source,
        )
    except Exception as e:  # noqa: BLE001
        if "SSL" in type(e).__name__ or "CERTIFICATE" in str(e).upper():
            print(
                "error: HTTPS certificate verification failed (Binance/Pyth). Try:\n"
                "  - Use the repo venv: .venv313/bin/python scripts/month_crt_wss.py …\n"
                "  - export SSL_CERT_FILE=$(python -c 'import certifi; print(certifi.where())')\n"
                "  - Or one-off: add --insecure-tls (research only)\n"
                f"Original: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return 2
        raise
    df = attach_signals_to_frame(df0, params=params)
    rs = pd.Timestamp(args.start, tz="UTC")
    re = pd.Timestamp(args.end, tz="UTC")
    m = (df.index >= rs) & (df.index < re)
    n_bars = int(m.sum())
    n_up = int((df.loc[m, "side"] == "UP").sum())
    n_dn = int((df.loc[m, "side"] == "DOWN").sum())
    n_sk = int((df.loc[m, "side"] == "SKIP").sum())
    print(f"bars_in_range={n_bars} UP={n_up} DOWN={n_dn} SKIP={n_sk}", flush=True)

    toy = summarize_toy_crt_trades(
        df,
        range_mask=m,
        stake_usd=float(args.toy_stake_usd),
        yes_entry_mid=float(args.toy_yes_mid),
        no_entry_mid=args.toy_no_mid,
        fee_roundtrip_bps=float(args.toy_fee_roundtrip_bps),
    )
    _print_toy_crt_table(
        toy,
        yes_mid=float(args.toy_yes_mid),
        fee_bps=float(args.toy_fee_roundtrip_bps),
        range_s=str(args.start),
        range_e=str(args.end),
        exec_interval=str(args.exec_interval),
    )

    if args.crt_bars_out is not None:
        rows = crt_bars_to_records(df, asset=args.asset, range_start=args.start, range_end=args.end)
        _write_jsonl(args.crt_bars_out, rows)
        print(f"wrote {len(rows)} crt_bar rows -> {args.crt_bars_out.resolve()}", flush=True)

    if args.skip_wss:
        return 0

    sim_p = WssMonthSimParams(
        tf_minutes=15,
        slug_offset_steps=int(args.slug_offset_steps),
        entry_mode=args.entry_mode,
        entry_end_buffer_sec=float(args.entry_end_buffer_sec),
        entry_first_minutes=float(args.entry_first_minutes),
        max_gamma_outcome_deviation=float(args.max_gamma_outcome_dev),
        skip_gamma=not bool(args.fetch_gamma),
        require_gamma_active=True,
        pullback_frac=float(args.pullback_frac),
        fib_lo=float(args.fib_lo),
        fib_hi=float(args.fib_hi),
    )
    sim_p = apply_wss_month_preset(sim_p, str(args.wss_preset))
    if str(args.wss_preset) == "coarse_spot":
        print(
            "wss preset=coarse_spot (relaxed pullback/fib/end-buffer; research — use binance_1m for realistic fills)",
            flush=True,
        )
    if args.wss_spot_source == "crt_15m" and str(args.wss_preset) == "default":
        print(
            "hint: crt_15m rarely produces paper_fill with default WSS gates; "
            "try --wss-preset coarse_spot for stress tests, or --wss-spot-source binance_1m when reachable.",
            flush=True,
        )

    if args.wss_spot_source == "crt_15m":
        spot_bars = df[["close"]].copy()
        print(f"wss spot=crt_15m rows={len(spot_bars)} (no Binance 1m)", flush=True)
    else:
        pair = binance_symbol(normalize_asset(args.asset))
        pad_lo = rs - pd.Timedelta(hours=6)
        pad_hi = re + pd.Timedelta(days=2)
        print(f"wss spot=binance_1m: {pair} {pad_lo} .. {pad_hi} UTC …", flush=True)
        try:
            spot_bars = prefetch_binance_1m_range(pair, pad_lo, pad_hi)
        except Exception as e:  # noqa: BLE001
            if "403" in str(e):
                print(
                    "error: Binance returned 403 (geo/datacenter block). Retry with:\n"
                    "  --wss-spot-source crt_15m [--wss-preset coarse_spot]\n"
                    "CRT 15m is coarse; coarse_spot relaxes gates for occasional paper_fill (research only).",
                    file=sys.stderr,
                )
                return 2
            raise
        print(f"1m rows={len(spot_bars)}", flush=True)

    sim_rows = simulate_wss_for_crt_frame(
        df,
        asset=args.asset,
        range_start=args.start,
        range_end=args.end,
        spot_bars=spot_bars,
        sim_p=sim_p,
    )
    wss_path = args.wss_out
    _write_jsonl(wss_path, sim_rows)
    fills = sum(1 for r in sim_rows if r.get("result") == "paper_fill")
    to = sum(1 for r in sim_rows if r.get("result") == "timeout")
    nd = sum(1 for r in sim_rows if r.get("result") in ("no_1m_data", "no_spot_data"))
    print(
        f"wss_sim windows={len(sim_rows)} paper_fill={fills} timeout={to} no_1m_data={nd} -> {wss_path.resolve()}",
        flush=True,
    )
    wss_pnl = summarize_wss_sim_fills(
        sim_rows,
        stake_usd=float(args.toy_stake_usd),
        yes_entry_mid=float(args.toy_yes_mid),
        no_entry_mid=args.toy_no_mid,
        fee_roundtrip_bps=float(args.toy_fee_roundtrip_bps),
    )
    print(
        "wss_pnl_proxy (first/last close in window vs toy stake/mids; see docstring): "
        f"settled={wss_pnl['settled_trades']} wins={wss_pnl['wins']} "
        f"ties={wss_pnl['settlement_ties']} wr={wss_pnl['win_rate']!s} "
        f"pnl_net_usd={float(wss_pnl['pnl_net_usd']):.2f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    reexec_if_needed(root=ROOT, script=Path(__file__).resolve())
    raise SystemExit(main())
