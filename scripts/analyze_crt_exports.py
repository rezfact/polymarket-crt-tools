#!/usr/bin/env python3
"""
Summarize exported ``crt_bar`` / ``wss_sim`` JSONL (e.g. from ``month_crt_wss.py``):

- SKIP reason counts (within optional UTC range)
- Toy win rate / PnL (next bar close vs signal bar open; same share model as ``summarize_toy_crt_trades``)
- Toy breakdown by **side** and by **htf_rp_c1** bucket
- Optional WSS sim: ``result`` histogram (and side × result)

Example::

  ./.venv313/bin/python scripts/analyze_crt_exports.py var/crt_test.jsonl
  ./.venv313/bin/python scripts/analyze_crt_exports.py var/crt_test.jsonl --wss var/wss_test.jsonl
  ./.venv313/bin/python scripts/analyze_crt_exports.py var/crt_bars_2026-01.jsonl \\
    --range-start 2026-01-01 --range-end 2026-01-08 --toy-stake-usd 10

WSS **paper_fill** rows include a window open/settle proxy; ``--wss`` adds WR/PnL (same stake/mids flags).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _print_md_table(headers: tuple[str, ...], rows: list[tuple[Any, ...]], aligns: tuple[str, ...]) -> None:
    """Markdown pipe table; aligns: 'l' or 'r' per column."""
    if not rows:
        print("_(no rows)_")
        return
    head = "| " + " | ".join(headers) + " |"
    sep_parts = []
    for j, (h, a) in enumerate(zip(headers, aligns, strict=True)):
        w = max(len(str(c)) for c in [h] + [row[j] for row in rows])
        if a == "r":
            sep_parts.append("-" * max(3, w) + ":")
        else:
            sep_parts.append(":" + "-" * max(3, w))
    sep = "| " + " | ".join(sep_parts) + " |"
    print(head)
    print(sep)
    for r in rows:
        cells = []
        for j, (c, a) in enumerate(zip(r, aligns, strict=True)):
            w = max(len(str(x)) for x in [headers[j]] + [row[j] for row in rows])
            s = str(c)
            if a == "r":
                cells.append(s.rjust(w))
            else:
                cells.append(s.ljust(w))
        print("| " + " | ".join(cells) + " |")


def _load_crt_records(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        if o.get("kind") != "crt_bar":
            raise ValueError(f"{path}: expected kind=crt_bar, got {o.get('kind')!r}")
        rows.append(o)
    rows.sort(key=lambda r: str(r.get("timestamp", "")))
    return rows


def _load_wss_records(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        if o.get("kind") != "wss_sim":
            raise ValueError(f"{path}: expected kind=wss_sim, got {o.get('kind')!r}")
        rows.append(o)
    return rows


def _htf_rp_bucket(rp: float) -> str:
    if rp < 0.25:
        return "[0.00, 0.25) deep_discount"
    if rp < 0.45:
        return "[0.25, 0.45) discount"
    if rp <= 0.55:
        return "[0.45, 0.55] mid"
    if rp <= 0.75:
        return "(0.55, 0.75] premium"
    return "(0.75, 1.00] deep_premium"


def _in_time_range(ts: str, lo: Any, hi: Any) -> bool:
    import pandas as pd

    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    ok = True
    if lo is not None:
        ok = ok and (t >= lo)
    if hi is not None:
        ok = ok and (t < hi)
    return bool(ok)


def main() -> int:
    p = argparse.ArgumentParser(description="Analyze crt_bar / wss_sim JSONL exports.")
    p.add_argument("crt_bars", type=Path, help="JSONL file with kind=crt_bar rows")
    p.add_argument("--wss", type=Path, default=None, help="Optional JSONL with kind=wss_sim rows")
    p.add_argument("--range-start", type=str, default=None, help="UTC inclusive (e.g. 2026-01-10)")
    p.add_argument("--range-end", type=str, default=None, help="UTC exclusive (e.g. 2026-01-12)")
    p.add_argument("--toy-stake-usd", type=float, default=10.0)
    p.add_argument("--toy-yes-mid", type=float, default=0.5)
    p.add_argument("--toy-no-mid", type=float, default=None)
    p.add_argument("--toy-fee-roundtrip-bps", type=float, default=0.0)
    p.add_argument(
        "--wss-pnl-use-gamma-entry",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="WSS PnL: use gamma_entry_mid_at_fill on each paper_fill when present",
    )
    args = p.parse_args()

    try:
        import pandas as pd

        from polymarket_htf.backtest_crt import (
            share_settlement,
            summarize_toy_crt_trades,
            summarize_wss_sim_fills,
        )
    except ModuleNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    crt_path = args.crt_bars
    if not crt_path.is_file():
        print(f"error: not a file: {crt_path}", file=sys.stderr)
        return 2

    records = _load_crt_records(crt_path)
    if not records:
        print("error: no crt_bar rows", file=sys.stderr)
        return 2

    rs = pd.Timestamp(args.range_start, tz="UTC") if args.range_start else None
    re = pd.Timestamp(args.range_end, tz="UTC") if args.range_end else None

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()

    m = pd.Series(True, index=df.index)
    if rs is not None:
        m &= df.index >= rs
    if re is not None:
        m &= df.index < re

    n_in = int(m.sum())
    print(f"# CRT bars: `{crt_path}`")
    print(f"rows_total={len(df)} rows_in_range={n_in}  range_start={args.range_start!r} range_end={args.range_end!r}")
    print()

    # SKIP reasons (only rows in range)
    reasons: Counter[str] = Counter()
    for ts, row in df.loc[m].iterrows():
        if str(row.get("side")) == "SKIP":
            reasons[str(row.get("reason", "?"))] += 1
    skip_n = sum(reasons.values())
    print("## SKIP reasons (in range)")
    if skip_n == 0:
        print("_(no SKIP rows in range)_\n")
    else:
        rrows = []
        for reason, cnt in reasons.most_common():
            rrows.append((reason, cnt, f"{100.0 * cnt / skip_n:.1f}%"))
        _print_md_table(("reason", "count", "pct_of_skips"), rrows, ("l", "r", "r"))
        print()

    # Overall toy (same as month_crt_wss)
    toy = summarize_toy_crt_trades(
        df,
        range_mask=m,
        stake_usd=float(args.toy_stake_usd),
        yes_entry_mid=float(args.toy_yes_mid),
        no_entry_mid=args.toy_no_mid,
        fee_roundtrip_bps=float(args.toy_fee_roundtrip_bps),
    )
    print("## Toy CRT (next bar close vs signal bar open — not Polymarket / Chainlink)")
    print(
        f"flat_stake_usd={toy['stake_usd']:.2f}  yes_mid={float(args.toy_yes_mid):.3f}  "
        f"fee_roundtrip_bps={float(args.toy_fee_roundtrip_bps):.1f}"
    )
    if int(toy["trades"]) == 0:
        print("_(no resolvable UP/DOWN in range)_\n")
    else:
        wr = float(toy["win_rate"] or 0.0)
        _print_md_table(
            ("trades", "wins", "losses", "win_rate", "pnl_gross_usd", "fees_usd", "pnl_net_usd"),
            [
                (
                    toy["trades"],
                    toy["wins"],
                    toy["losses"],
                    f"{wr * 100:.2f}%",
                    f"{float(toy['pnl_gross_usd']):.2f}",
                    f"{float(toy['fees_usd']):.2f}",
                    f"{float(toy['pnl_net_usd']):.2f}",
                )
            ],
            ("r", "r", "r", "r", "r", "r", "r"),
        )
        print()

    # Per-side and per-bucket: walk ordered records for index alignment with "next" row
    fee_rt = float(args.toy_fee_roundtrip_bps) / 10_000.0
    stake = float(args.toy_stake_usd)
    yes_mid = float(args.toy_yes_mid)
    no_mid = args.toy_no_mid

    def one_trade(sig: str, win: bool) -> tuple[float, float]:
        st = share_settlement(usdc_spent=stake, win=win, side=sig, yes_mid=yes_mid, no_mid=no_mid)
        fee = stake * fee_rt
        return st.pnl_gross, fee

    by_side: dict[str, list[tuple[bool, float, float]]] = defaultdict(list)
    by_bucket: dict[str, list[tuple[bool, float, float]]] = defaultdict(list)

    for i, r in enumerate(records):
        ts = str(r["timestamp"])
        if rs is not None or re is not None:
            if not _in_time_range(ts, rs, re):
                continue
        sig = str(r.get("side", "SKIP"))
        if sig not in ("UP", "DOWN"):
            continue
        if i + 1 >= len(records):
            continue
        nxt = records[i + 1]
        o_open = float(r["open"])
        n_close = float(nxt["close"])
        toy_up = n_close > o_open
        win = bool((sig == "UP" and toy_up) or (sig == "DOWN" and (not toy_up)))
        g, fe = one_trade(sig, win)
        net = g - fe
        by_side[sig].append((win, g, net))
        rp = float(r["htf_rp_c1"])
        by_bucket[_htf_rp_bucket(rp)].append((win, g, net))

    print("## Toy by side (in range)")
    srows = []
    for side in ("UP", "DOWN"):
        xs = by_side.get(side, [])
        if not xs:
            srows.append((side, 0, 0, 0, "—", "0.00", "0.00"))
            continue
        n = len(xs)
        w = sum(1 for x in xs if x[0])
        pnl = sum(x[2] for x in xs)
        srows.append((side, n, w, n - w, f"{w / n:.2%}", f"{sum(x[1] for x in xs):.2f}", f"{pnl:.2f}"))
    _print_md_table(("side", "trades", "wins", "losses", "win_rate", "pnl_gross_usd", "pnl_net_usd"), srows, ("l", "r", "r", "r", "r", "r", "r"))
    print()

    print("## Toy by htf_rp_c1 bucket (in range)")
    bucket_order = [
        "[0.00, 0.25) deep_discount",
        "[0.25, 0.45) discount",
        "[0.45, 0.55] mid",
        "(0.55, 0.75] premium",
        "(0.75, 1.00] deep_premium",
    ]
    brows = []
    for b in bucket_order:
        xs = by_bucket.get(b, [])
        if not xs:
            brows.append((b, 0, 0, 0, "—", "0.00", "0.00"))
            continue
        n = len(xs)
        w = sum(1 for x in xs if x[0])
        pnl = sum(x[2] for x in xs)
        brows.append((b, n, w, n - w, f"{w / n:.2%}", f"{sum(x[1] for x in xs):.2f}", f"{pnl:.2f}"))
    _print_md_table(
        ("htf_rp_bucket", "trades", "wins", "losses", "win_rate", "pnl_gross_usd", "pnl_net_usd"),
        brows,
        ("l", "r", "r", "r", "r", "r", "r"),
    )
    print()

    if args.wss is None:
        return 0

    wss_path = args.wss
    if not wss_path.is_file():
        print(f"error: --wss not a file: {wss_path}", file=sys.stderr)
        return 2
    wss_rows = _load_wss_records(wss_path)

    def _wss_row_in_range(r: dict[str, Any]) -> bool:
        if rs is None and re is None:
            return True
        ts = str(r.get("arm_bar_ts") or "")
        if not ts:
            return False
        return _in_time_range(ts, rs, re)

    wss_in = [r for r in wss_rows if _wss_row_in_range(r)]
    print(f"# WSS sim: `{wss_path}`")
    print(f"rows={len(wss_rows)} rows_in_range={len(wss_in)}  range_start={args.range_start!r} range_end={args.range_end!r}")
    print()
    print("## WSS result (rows in range)")
    rc: Counter[str] = Counter(str(r.get("result", "?")) for r in wss_in)
    total = len(wss_in) or 1
    wrows = [(res, cnt, f"{100.0 * cnt / total:.1f}%") for res, cnt in rc.most_common()]
    _print_md_table(("result", "count", "pct"), wrows, ("l", "r", "r"))
    print()

    print("## WSS result × side (in range)")
    cross: Counter[tuple[str, str]] = Counter()
    for r in wss_in:
        cross[(str(r.get("side", "?")), str(r.get("result", "?")))] += 1
    crows = [(a, b, c) for (a, b), c in sorted(cross.items())]
    _print_md_table(("side", "result", "count"), crows, ("l", "l", "r"))
    print()

    wpnl = summarize_wss_sim_fills(
        wss_in,
        stake_usd=float(args.toy_stake_usd),
        yes_entry_mid=float(args.toy_yes_mid),
        no_entry_mid=args.toy_no_mid,
        fee_roundtrip_bps=float(args.toy_fee_roundtrip_bps),
        use_gamma_entry_mid_at_fill=bool(args.wss_pnl_use_gamma_entry),
    )
    print("## WSS paper_fill — proxy settlement WR / PnL (flat stake, share mids)")
    print(
        f"first/last close in each window; stake_usd={wpnl['stake_usd']:.2f} "
        f"entry={'gamma_entry_mid_at_fill' if args.wss_pnl_use_gamma_entry else f'yes_mid={float(args.toy_yes_mid):.3f}'} "
        f"fee_roundtrip_bps={float(args.toy_fee_roundtrip_bps):.1f}"
    )
    if int(wpnl["paper_fills"]) == 0:
        print("_(no paper_fill rows in range)_\n")
    else:
        wrs = wpnl["win_rate"]
        wr_cell = "—" if wrs is None else f"{float(wrs) * 100:.2f}%"
        _print_md_table(
            (
                "paper_fills",
                "settled",
                "ties",
                "wins",
                "losses",
                "win_rate",
                "pnl_gross_usd",
                "fees_usd",
                "pnl_net_usd",
            ),
            [
                (
                    wpnl["paper_fills"],
                    wpnl["settled_trades"],
                    wpnl["settlement_ties"],
                    wpnl["wins"],
                    wpnl["losses"],
                    wr_cell,
                    f"{float(wpnl['pnl_gross_usd']):.2f}",
                    f"{float(wpnl['fees_usd']):.2f}",
                    f"{float(wpnl['pnl_net_usd']):.2f}",
                )
            ],
            ("r", "r", "r", "r", "r", "r", "r", "r", "r"),
        )
        if int(wpnl.get("legacy_missing_settlement") or 0) > 0:
            print(
                f"_(warn: {wpnl['legacy_missing_settlement']} paper_fill rows lack settlement fields — re-run month_crt_wss)_"
            )
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
