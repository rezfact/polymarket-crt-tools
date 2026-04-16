from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from polymarket_htf.assets import binance_symbol, normalize_asset
from polymarket_htf.crt_strategy import CRTParams, build_exec_frame, crt_signal_row
from polymarket_htf.gamma import (
    build_updown_slug,
    exec_interval_to_polymarket_tf_minutes,
    updown_window_open_epoch,
)
from polymarket_htf.sizing import trade_usd_from_capital


def _utc(ts: str | pd.Timestamp) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.tz_localize("UTC")
    return t.tz_convert("UTC")


@dataclass
class BacktestAccountConfig:
    """
    Polymarket-style **shares** PnL (research simplification):

    - You spend ``usdc`` (here = position size from sizing rules).
    - You buy **shares** at ``entry_price`` USD per share (0–1 on Polymarket).
    - ``shares = usdc / entry_price``.
    - If the market resolves in your favor, each share redeems **$1** → ``redemption = shares``; else **$0**.
    - Gross PnL = ``redemption - usdc`` (same as before, but recorded explicitly).
    """

    initial_capital: float = 10_000.0
    # Mid / average fill for **YES** when betting UP (USD per $1 payoff share).
    yes_entry_mid: float = 0.5
    # Mid for **NO** when betting DOWN; default ``None`` → ``1 - yes_entry_mid`` (complement).
    no_entry_mid: float | None = None
    # Round-trip fees as fraction of **usdc** (single knob): 100 bps = 1% of stake per trade.
    fee_roundtrip_bps: float = 0.0
    # Per-trade USDC cap (see :func:`polymarket_htf.sizing.trade_usd_from_capital`); ``None`` = no cap.
    max_stake_usd: float | None = 10.0
    # Optional take-profit ladder on a **linear mark bridge** to the toy terminal (0/1); see
    # :func:`polymarket_htf.take_profit_ladder.simulate_tp_ladder_on_bridge`.
    take_profit_tiers: str | None = None
    take_profit_bridge_steps: int = 64


@dataclass(frozen=True)
class ShareSettlement:
    """One closed position in share economics."""

    usdc_spent: float
    entry_price: float
    shares: float
    redemption_usd: float
    pnl_gross: float


@dataclass
class BacktestSummary:
    asset: str
    trades: int
    wins: int
    skips: int
    hit_rate: float | None
    initial_capital: float
    final_capital: float
    total_fees: float
    total_pnl: float
    trade_events: list[dict] = field(default_factory=list)


def _forward_up_label(df: pd.DataFrame) -> pd.Series:
    """Toy label: next bar close vs **this** bar open (not Chainlink window)."""
    nxt = df["close"].shift(-1)
    return (nxt > df["open"]).astype("float")


def _clamp_mid(p: float) -> float:
    return float(min(0.99, max(0.01, p)))


def _entry_price_for_side(*, side: str, yes_mid: float, no_mid: float | None) -> float:
    p_yes = _clamp_mid(yes_mid)
    if side == "UP":
        return p_yes
    if no_mid is not None:
        return _clamp_mid(no_mid)
    return _clamp_mid(1.0 - p_yes)


def share_settlement(
    *,
    usdc_spent: float,
    win: bool,
    side: str,
    yes_mid: float,
    no_mid: float | None = None,
) -> ShareSettlement:
    """Polymarket-like: buy outcome shares with USDC, redeem $1 per share if you win."""
    p = _entry_price_for_side(side=side, yes_mid=yes_mid, no_mid=no_mid)
    shares = usdc_spent / p
    redemption = shares if win else 0.0
    pnl_gross = redemption - usdc_spent
    return ShareSettlement(
        usdc_spent=usdc_spent,
        entry_price=p,
        shares=shares,
        redemption_usd=redemption,
        pnl_gross=pnl_gross,
    )


def _pnl_binary(*, stake: float, win: bool, side: str, yes_mid: float, no_mid: float | None = None) -> float:
    """Backward-compatible gross PnL (delegates to :func:`share_settlement`)."""
    return share_settlement(
        usdc_spent=stake, win=win, side=side, yes_mid=yes_mid, no_mid=no_mid
    ).pnl_gross


def summarize_toy_crt_trades(
    df: pd.DataFrame,
    *,
    range_mask: pd.Series,
    stake_usd: float,
    yes_entry_mid: float = 0.5,
    no_entry_mid: float | None = None,
    fee_roundtrip_bps: float = 0.0,
) -> dict[str, float | int | None]:
    """
    Per-signal **toy** stats over ``range_mask``: next bar's close vs this bar's open
    (same as :func:`_forward_up_label` / :func:`run_crt_backtest`). Each trade uses a flat
    ``stake_usd`` and share entry mids; **not** Polymarket / Chainlink resolution.
    """
    if isinstance(range_mask, pd.Series):
        rm = range_mask.reindex(df.index, fill_value=False).astype(bool)
    else:
        arr = np.asarray(range_mask, dtype=bool)
        if arr.shape[0] != len(df):
            raise ValueError("range_mask length must match df")
        rm = pd.Series(arr, index=df.index, dtype=bool)
    fwd = _forward_up_label(df)
    fee_rt = fee_roundtrip_bps / 10_000.0
    trades = 0
    wins = 0
    pnl_gross_sum = 0.0
    fee_sum = 0.0
    for ts, row in df.loc[rm].iterrows():
        sig = str(row.get("side", row.get("signal", "SKIP")))
        if sig not in ("UP", "DOWN"):
            continue
        fu = fwd.loc[ts]
        if pd.isna(fu):
            continue
        fu_f = float(fu)
        win = (sig == "UP" and fu_f == 1.0) or (sig == "DOWN" and fu_f == 0.0)
        st = share_settlement(
            usdc_spent=float(stake_usd),
            win=win,
            side=sig,
            yes_mid=float(yes_entry_mid),
            no_mid=no_entry_mid,
        )
        fee = float(stake_usd) * fee_rt
        trades += 1
        if win:
            wins += 1
        pnl_gross_sum += st.pnl_gross
        fee_sum += fee
    pnl_net = pnl_gross_sum - fee_sum
    wr: float | None
    if trades:
        wr = wins / trades
    else:
        wr = None
    return {
        "trades": trades,
        "wins": wins,
        "losses": trades - wins,
        "win_rate": wr,
        "pnl_gross_usd": pnl_gross_sum,
        "fees_usd": fee_sum,
        "pnl_net_usd": pnl_net,
        "stake_usd": float(stake_usd),
    }


def summarize_wss_sim_fills(
    rows: Iterable[dict[str, Any]],
    *,
    stake_usd: float,
    yes_entry_mid: float = 0.5,
    no_entry_mid: float | None = None,
    fee_roundtrip_bps: float = 0.0,
    use_gamma_entry_mid_at_fill: bool = False,
) -> dict[str, float | int | None]:
    """
    Win rate and share-model PnL on ``kind=wss_sim`` rows with ``result=paper_fill``.

    Expects settlement fields from :func:`polymarket_htf.crt_wss_monthly.wss_proxy_settlement_from_slice`
    (``side_win``, ``settlement_tie``). Ties are counted but excluded from WR denominator.

    When ``use_gamma_entry_mid_at_fill`` is True and a row has ``gamma_entry_mid_at_fill``, that value
    is used as the **side** entry price (YES mid for UP, NO mid for DOWN); rows missing it fall back
    to ``yes_entry_mid`` / ``no_entry_mid``.
    """
    fee_rt = float(fee_roundtrip_bps) / 10_000.0
    n_fill = 0
    n_tie = 0
    n_missing = 0
    settled = 0
    wins = 0
    pnl_gross_sum = 0.0
    fee_sum = 0.0
    for r in rows:
        if str(r.get("kind", "")) != "wss_sim" or str(r.get("result", "")) != "paper_fill":
            continue
        n_fill += 1
        if bool(r.get("settlement_tie")):
            n_tie += 1
            continue
        sw = r.get("side_win")
        if sw is None:
            n_missing += 1
            continue
        settled += 1
        win = bool(sw)
        if win:
            wins += 1
        side = str(r.get("side", "SKIP"))
        yes_m = float(yes_entry_mid)
        no_m = no_entry_mid
        if use_gamma_entry_mid_at_fill:
            gfill = r.get("gamma_entry_mid_at_fill")
            if gfill is not None:
                try:
                    gp = float(gfill)
                except (TypeError, ValueError):
                    gp = None
                if gp is not None:
                    if side == "UP":
                        yes_m = gp
                    elif side == "DOWN":
                        no_m = gp
        st = share_settlement(
            usdc_spent=float(stake_usd),
            win=win,
            side=side,
            yes_mid=yes_m,
            no_mid=no_m,
        )
        fee = float(stake_usd) * fee_rt
        pnl_gross_sum += st.pnl_gross
        fee_sum += fee
    pnl_net = pnl_gross_sum - fee_sum
    wr: float | None = (wins / settled) if settled else None
    return {
        "paper_fills": n_fill,
        "settlement_ties": n_tie,
        "legacy_missing_settlement": n_missing,
        "settled_trades": settled,
        "wins": wins,
        "losses": settled - wins,
        "win_rate": wr,
        "pnl_gross_usd": pnl_gross_sum,
        "fees_usd": fee_sum,
        "pnl_net_usd": pnl_net,
        "stake_usd": float(stake_usd),
    }


def run_crt_backtest(
    asset: str,
    *,
    params: CRTParams | None = None,
    account: BacktestAccountConfig | None = None,
    range_start: str | pd.Timestamp | None = None,
    range_end: str | pd.Timestamp | None = None,
    warmup_days: float = 45.0,
    use_binance_vision: bool = False,
    vision_cache_dir: Path | str | None = None,
    vision_origin: str | None = None,
    price_source: Literal["binance", "pyth"] = "pyth",
) -> tuple[pd.DataFrame, BacktestSummary]:
    params = params or CRTParams()
    acct = account or BacktestAccountConfig()
    a = normalize_asset(asset)
    pair = binance_symbol(a)
    rs = _utc(range_start) if range_start is not None else None
    re = _utc(range_end) if range_end is not None else None
    if (rs is None) ^ (re is None):
        raise ValueError("Provide both range_start and range_end, or neither.")
    df = build_exec_frame(
        binance_pair=pair,
        params=params,
        range_start=rs,
        range_end=re,
        warmup_days=warmup_days,
        use_binance_vision=use_binance_vision,
        vision_cache_dir=vision_cache_dir,
        vision_origin=vision_origin,
        price_source=price_source,
    )
    sides: list[str] = []
    reasons: list[str] = []
    for _, row in df.iterrows():
        s, r = crt_signal_row(row, params=params)
        sides.append(s)
        reasons.append(r)
    df["signal"] = sides
    df["reason"] = reasons
    df["fwd_up"] = _forward_up_label(df)

    capital = float(acct.initial_capital)
    total_fees = 0.0
    wins = 0
    trades = 0
    events: list[dict] = []
    fee_rt = float(acct.fee_roundtrip_bps) / 10_000.0

    for i in range(len(df) - 1):
        ts = df.index[i]
        if rs is not None and ts < rs:
            continue
        if re is not None and ts >= re:
            continue
        sig = str(df["signal"].iloc[i])
        if sig == "SKIP":
            continue
        stake = trade_usd_from_capital(capital, max_stake_usd=acct.max_stake_usd)
        if stake <= 0:
            break
        fu = df["fwd_up"].iloc[i]
        if pd.isna(fu):
            continue
        win = bool((sig == "UP" and fu == 1.0) or (sig == "DOWN" and fu == 0.0))
        if win:
            wins += 1
        trades += 1
        settle = share_settlement(
            usdc_spent=stake,
            win=win,
            side=sig,
            yes_mid=acct.yes_entry_mid,
            no_mid=acct.no_entry_mid,
        )
        tp_events: list[dict] = []
        if acct.take_profit_tiers:
            from polymarket_htf.take_profit_ladder import parse_tiers_spec, simulate_tp_ladder_on_bridge

            tiers = parse_tiers_spec(acct.take_profit_tiers)
            tp = simulate_tp_ladder_on_bridge(
                usdc_spent=stake,
                entry_price=settle.entry_price,
                shares=settle.shares,
                terminal_price=1.0 if win else 0.0,
                tiers=tiers,
                bridge_steps=max(2, int(acct.take_profit_bridge_steps)),
            )
            tp_events = list(tp.events)
            settle = replace(
                settle,
                redemption_usd=tp.cash_from_sales + tp.final_redemption_usd,
                pnl_gross=tp.pnl_gross,
            )
        fee = stake * fee_rt
        pnl_net = settle.pnl_gross - fee
        capital_before = capital
        capital += pnl_net
        total_fees += fee
        row = df.iloc[i]
        nxt = df.iloc[i + 1]
        tfm = exec_interval_to_polymarket_tf_minutes(str(params.exec_interval))
        toy_up = float(nxt["close"]) > float(row["open"])
        slug: str | None = None
        woe: int | None = None
        if tfm is not None:
            woe = updown_window_open_epoch(ts_utc=ts, tf_minutes=tfm)
            slug = build_updown_slug(a, tf_minutes=tfm, window_open_ts=woe)
        events.append(
            {
                "i": i,
                "timestamp": str(ts),
                "side": sig,
                "reason": str(df["reason"].iloc[i]),
                "exec_interval": str(params.exec_interval),
                "capital_before": capital_before,
                "usdc_spent": stake,
                "entry_price": settle.entry_price,
                "shares": settle.shares,
                "redemption_usd": settle.redemption_usd,
                "win": win,
                "pnl_gross": settle.pnl_gross,
                "fee_usd": fee,
                "pnl_net": pnl_net,
                "capital_after": capital,
                "polymarket_slug": slug,
                "window_open_epoch": woe,
                "btc_signal_bar_open": float(row["open"]),
                "btc_signal_bar_high": float(row["high"]),
                "btc_signal_bar_low": float(row["low"]),
                "btc_signal_bar_close": float(row["close"]),
                "btc_next_bar_open": float(nxt["open"]),
                "btc_next_bar_high": float(nxt["high"]),
                "btc_next_bar_low": float(nxt["low"]),
                "btc_next_bar_close": float(nxt["close"]),
                "toy_resolution_up": toy_up,
                "settlement_proxy": "next_bar_close_gt_signal_bar_open",
                "yes_entry_mid": float(acct.yes_entry_mid),
                "no_entry_mid": float(acct.no_entry_mid) if acct.no_entry_mid is not None else None,
                "take_profit_sim": bool(acct.take_profit_tiers),
                "take_profit_bridge_steps": int(acct.take_profit_bridge_steps) if acct.take_profit_tiers else None,
                "take_profit_events": tp_events if acct.take_profit_tiers else [],
            }
        )
        if capital < 1.0:
            break

    if rs is not None or re is not None:
        m = pd.Series(True, index=df.index)
        if rs is not None:
            m &= df.index >= rs
        if re is not None:
            m &= df.index < re
        skips = int(((df["signal"] == "SKIP") & m).sum())
    else:
        skips = int((df["signal"] == "SKIP").sum())
    hit = (wins / trades) if trades else None
    summary = BacktestSummary(
        asset=a,
        trades=trades,
        wins=wins,
        skips=skips,
        hit_rate=hit,
        initial_capital=float(acct.initial_capital),
        final_capital=capital,
        total_fees=total_fees,
        total_pnl=capital - float(acct.initial_capital),
        trade_events=events,
    )
    return df, summary
