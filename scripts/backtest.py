#!/usr/bin/env python3
"""CRT-style backtest (Binance OHLC proxy — not Polymarket settlement)."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fmt_trade_line(ev: dict) -> str:
    w = "W" if ev["win"] else "L"
    return (
        f"{ev['timestamp']} {w} {ev['side']:4} "
        f"cap={ev['capital_before']:.2f}→{ev['capital_after']:.2f} "
        f"usdc={ev['usdc_spent']:.2f} p={ev['entry_price']:.4f} "
        f"shares={ev['shares']:.4f} redeem={ev['redemption_usd']:.4f} "
        f"pnl_net={ev['pnl_net']:.4f}"
    )


def _dump_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


def _compounding_explain(summary, *, yes_mid: float, no_mid: float | None) -> None:
    evs = summary.trade_events
    if not evs:
        print("\n(no trades in range — nothing to explain)")
        return
    p_yes = min(0.99, max(0.01, yes_mid))
    p_no = min(0.99, max(0.01, no_mid if no_mid is not None else 1.0 - yes_mid))
    up_mult = 1.0 / p_yes - 1.0
    down_mult = 1.0 / p_no - 1.0
    wins = [e for e in evs if e["win"]]
    losses = [e for e in evs if not e["win"]]
    gross_win = sum(e["pnl_gross"] for e in wins)
    gross_lose = sum(e["pnl_gross"] for e in losses)
    max_streak = cur = 0
    for e in evs:
        if e["win"]:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0
    last_stake = evs[-1]["usdc_spent"]
    last_cap = evs[-1]["capital_after"]
    print("\n--- Why compounding gets huge (this backtest) ---")
    print(
        f"Polymarket-style fills: UP buys YES at {p_yes:.4f} $/share → each WIN pays gross "
        f"+{up_mult:.1%} of USDC spent on that trade; DOWN buys NO at {p_no:.4f} → WIN pays +{down_mult:.1%}."
    )
    print(
        "Position size rule: USDC spent = max($1, floor(10% × capital_before)), "
        "so every time bankroll rises, the next trade risks more dollars at the same win multiple."
    )
    print(
        f"In this window: trades={len(evs)} wins={len(wins)} losses={len(losses)} "
        f"gross_from_wins={gross_win:.2f} gross_from_losses={gross_lose:.2f} "
        f"max_win_streak={max_streak} final_capital≈{last_cap:.2f} (last usdc_spent={last_stake:.2f})."
    )
    print(
        "Toy resolution label (not Chainlink): next bar close vs this bar open — not Polymarket reality."
    )
    print(
        "JSONL rows (with --dump-trades): polymarket_slug/window use NY grid; "
        "btc_* bars are the backtest OHLC feed; toy_resolution_up matches the toy label, "
        "not on-chain Chainlink start/end."
    )
    print("\n--- First 12 trades ---")
    for e in evs[:12]:
        print(_fmt_trade_line(e))
    print("\n--- Last 12 trades ---")
    for e in evs[-12:]:
        print(_fmt_trade_line(e))


def main() -> int:
    p = argparse.ArgumentParser(description="CRT mechanical backtest on Binance candles.")
    p.add_argument("--asset", default="btc", help="btc | eth | sol")
    p.add_argument("--exec-interval", default="15m", choices=["5m", "15m", "1h"])
    p.add_argument("--context-interval", default="1h", choices=["15m", "30m", "1h", "4h"])
    p.add_argument("--range-lookback", type=int, default=24)
    p.add_argument("--initial-capital", type=float, default=10_000.0, help="starting bankroll (USD)")
    p.add_argument(
        "--yes-entry-mid",
        type=float,
        default=0.5,
        help="assumed YES $/share fill for UP (Polymarket-style)",
    )
    p.add_argument(
        "--no-entry-mid",
        type=float,
        default=None,
        help="assumed NO $/share fill for DOWN (default: 1 - yes-entry-mid)",
    )
    p.add_argument(
        "--fee-roundtrip-bps",
        type=float,
        default=0.0,
        help="fees as bps of stake per closed trade (100 = 1%% of stake); approximates both sides",
    )
    p.add_argument(
        "--start",
        type=str,
        default=None,
        help="UTC range start (inclusive), e.g. 2026-01-01 — requires --end; uses Binance klines",
    )
    p.add_argument(
        "--end",
        type=str,
        default=None,
        help="UTC range end (**exclusive**), e.g. 2026-04-01 for all of Q1 2026",
    )
    p.add_argument(
        "--warmup-days",
        type=float,
        default=45.0,
        help="extra history before --start for indicators (fetched from Binance)",
    )
    p.add_argument(
        "--price-source",
        choices=["binance", "pyth"],
        default="pyth",
        help="OHLC source: Pyth Benchmarks TV (default; no Binance) vs Binance REST/Vision",
    )
    p.add_argument(
        "--spot-vision",
        action="store_true",
        help="load range from data.binance.vision spot monthly zips (not REST; not futures UM)",
    )
    p.add_argument(
        "--vision-cache-dir",
        type=Path,
        default=None,
        help="cache directory for Vision zips (default: ./data/binance_vision)",
    )
    p.add_argument(
        "--vision-origin",
        type=str,
        default=None,
        help="override Vision host (default: https://data.binance.vision)",
    )
    p.add_argument(
        "--crt-no-htf-filter",
        action="store_true",
        help="CRT: do not require Candle-1 close in HTF discount/premium zone",
    )
    p.add_argument(
        "--crt-preset",
        choices=["default", "loose", "loose_htf", "loose_plus"],
        default="default",
        help="CRT bundle to cut SKIPs (see polymarket_htf.crt_presets)",
    )
    p.add_argument(
        "--tp-tiers",
        type=str,
        default=None,
        metavar="SPEC",
        help='take-profit ladder on linear mark bridge to toy 0/1, e.g. "500:0.5,1000:1" (see take_profit_ladder)',
    )
    p.add_argument(
        "--tp-bridge-steps",
        type=int,
        default=64,
        help="evaluation points along entry→terminal linear path when --tp-tiers is set (default 64)",
    )
    p.add_argument(
        "--dump-trades",
        nargs="?",
        const="var/trades_dump.jsonl",
        default=None,
        metavar="PATH",
        help="write every filled trade as JSONL (default: var/trades_dump.jsonl); prints compounding explanation",
    )
    p.add_argument(
        "--print-all-trades",
        action="store_true",
        help="print every trade line to stdout (can be long); use with --dump-trades or alone",
    )
    args = p.parse_args()
    if args.spot_vision and (not args.start or not args.end):
        p.error("--spot-vision requires --start and --end (UTC range backtest).")
    if args.spot_vision and args.price_source == "pyth":
        p.error("--spot-vision cannot be combined with --price-source pyth.")

    from polymarket_htf.config_env import ensure_certifi_ssl_env, load_dotenv_files

    load_dotenv_files(project_root=ROOT)
    ensure_certifi_ssl_env()

    from polymarket_htf.crt_presets import apply_crt_preset
    from polymarket_htf.crt_strategy import CRTParams
    from polymarket_htf.backtest_crt import BacktestAccountConfig, run_crt_backtest

    params = CRTParams(
        exec_interval=args.exec_interval,  # type: ignore[arg-type]
        context_interval=args.context_interval,  # type: ignore[arg-type]
        range_lookback=args.range_lookback,
        use_htf_location_filter=not args.crt_no_htf_filter,
    )
    params = apply_crt_preset(params, args.crt_preset)
    if args.crt_no_htf_filter:
        params = replace(params, use_htf_location_filter=False)
    acct = BacktestAccountConfig(
        initial_capital=args.initial_capital,
        yes_entry_mid=args.yes_entry_mid,
        no_entry_mid=args.no_entry_mid,
        fee_roundtrip_bps=args.fee_roundtrip_bps,
        take_profit_tiers=args.tp_tiers,
        take_profit_bridge_steps=max(2, int(args.tp_bridge_steps)),
    )
    _, summary = run_crt_backtest(
        args.asset,
        params=params,
        account=acct,
        range_start=args.start,
        range_end=args.end,
        warmup_days=args.warmup_days,
        use_binance_vision=args.spot_vision,
        vision_cache_dir=args.vision_cache_dir,
        vision_origin=args.vision_origin,
        price_source=args.price_source,
    )
    hr = f"{summary.hit_rate:.1%}" if summary.hit_rate is not None else "n/a"
    src = ""
    if args.spot_vision:
        src += " vision=spot_monthly"
    if args.price_source == "pyth":
        src += " price=pyth_benchmarks_tv"
    rng = f" range={args.start}..{args.end} (UTC end exclusive)" if args.start else ""
    print(
        f"asset={summary.asset} trades={summary.trades} wins={summary.wins} "
        f"skips={summary.skips} hit_rate={hr}{rng}{src}"
    )
    print(
        f"capital: initial={summary.initial_capital:.2f} final={summary.final_capital:.2f} "
        f"pnl={summary.total_pnl:.2f} fees_paid={summary.total_fees:.2f}"
    )
    if args.tp_tiers:
        print(
            "note: take-profit uses a **linear synthetic mark path** to the toy terminal (not real Polymarket mids)."
        )
    if summary.trade_events and (args.dump_trades is not None or args.print_all_trades):
        if args.dump_trades is not None:
            outp = Path(args.dump_trades)
            _dump_jsonl(outp, summary.trade_events)
            print(f"\nwrote {len(summary.trade_events)} trades -> {outp.resolve()}")
        _compounding_explain(summary, yes_mid=args.yes_entry_mid, no_mid=args.no_entry_mid)
        if args.print_all_trades:
            print("\n--- All trades ---")
            for e in summary.trade_events:
                print(_fmt_trade_line(e))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
