#!/usr/bin/env python3
"""
Toy outcome for each dryrun **UP/DOWN** row (same rule as CRT backtest):

- **UP** wins iff next 15m bar **close** > this bar **open**
- **DOWN** wins iff next 15m bar **close** < this bar **open**

Uses Pyth Benchmarks OHLC (not Polymarket settlement). Dryrun itself opens **no** positions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("journal", type=Path)
    args = p.parse_args()

    from polymarket_htf.assets import binance_symbol, normalize_asset
    from polymarket_htf.pyth_prices import fetch_pyth_klines_range

    rows: list[dict] = []
    with args.journal.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    signals = []
    for r in rows:
        if r.get("kind") != "dryrun":
            continue
        sig = r.get("signal") or {}
        side = str(sig.get("side", "SKIP"))
        if side not in ("UP", "DOWN"):
            continue
        ts = sig.get("timestamp")
        if not ts:
            continue
        signals.append((r.get("asset"), side, ts, float(sig["open"]), r))

    if not signals:
        print("no UP/DOWN rows in journal")
        return 0

    wins = 0
    print(f"{'asset':<5} {'side':<5} {'bar_open_utc':<26} {'open':>14} {'next_close':>14} {'toy_win':>8}")
    for asset, side, ts, o_open, _raw in signals:
        a = normalize_asset(str(asset))
        sym = binance_symbol(a)
        from polymarket_htf.assets import pyth_tv_symbol_for_binance_pair

        pyth_sym = pyth_tv_symbol_for_binance_pair(sym)
        t0 = pd.Timestamp(ts)
        if t0.tzinfo is None:
            t0 = t0.tz_localize("UTC")
        else:
            t0 = t0.tz_convert("UTC")
        t1 = t0 + pd.Timedelta(minutes=45)
        df = fetch_pyth_klines_range("15m", symbol=pyth_sym, since=t0, until=t1)
        if df.empty or len(df) < 2:
            print(f"{a:<5} {side:<5} {str(ts):<26} {o_open:>14.4f} {'(no data)':>14} {'?':>8}")
            continue
        df = df.sort_index()
        i0 = None
        for i, idx in enumerate(df.index):
            if abs((idx - t0).total_seconds()) < 120:
                i0 = i
                break
        if i0 is None:
            i0 = 0
        if i0 + 1 >= len(df):
            print(f"{a:<5} {side:<5} {str(ts):<26} {o_open:>14.4f} {'(short)':>14} {'?':>8}")
            continue
        next_close = float(df.iloc[i0 + 1]["close"])
        if side == "UP":
            win = next_close > o_open
        else:
            win = next_close < o_open
        wins += int(win)
        print(
            f"{a:<5} {side:<5} {str(ts):<26} {o_open:>14.4f} {next_close:>14.4f} {str(win):>8}"
        )

    n = len(signals)
    print(f"\nrows={n} toy_wins={wins} toy_losses={n - wins} toy_hit_rate={wins / n:.1%}" if n else "")
    print("(toy = next 15m Pyth close vs signal bar open; not Polymarket PnL)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
