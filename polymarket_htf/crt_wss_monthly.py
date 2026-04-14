"""
Month-range **CRT bar export** + **WSS-style entry simulation** (research / batch).

CRT OHLC uses :func:`polymarket_htf.crt_strategy.build_exec_frame` (Pyth by default, or Binance / Vision).

WSS simulation can use **Binance 1m closes** as a Chainlink **spot proxy** (or ``crt_15m`` / presets) inside each Polymarket
``[T, T_end)`` window (same pullback / fib / entry-window rules as :class:`SweetSpotWatchParams`).
Gamma checks are optional (``skip_gamma=True`` avoids HTTP during long runs).
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Literal

import pandas as pd

from polymarket_htf.assets import binance_symbol, normalize_asset
from polymarket_htf.crt_strategy import CRTParams, build_exec_frame, crt_signal_row
from polymarket_htf.data import fetch_binance_klines_range
from polymarket_htf.fib_entry import fib_pullback_zone, spot_in_fib_zone
from polymarket_htf.gamma import (
    build_updown_slug,
    exec_interval_to_polymarket_tf_minutes,
    fetch_event_by_slug,
    gamma_outcome_sum_deviation,
    next_monitor_window_open_epoch,
)


def _utc(ts: str | pd.Timestamp) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.tz_localize("UTC")
    return t.tz_convert("UTC")


def build_crt_frame_for_range(
    asset: str,
    *,
    params: CRTParams,
    range_start: str | pd.Timestamp,
    range_end: str | pd.Timestamp,
    warmup_days: float = 45.0,
    use_binance_vision: bool = False,
    vision_cache_dir: Any = None,
    vision_origin: str | None = None,
    price_source: Literal["binance", "pyth"] = "pyth",
) -> pd.DataFrame:
    """OHLC + CRT columns for ``[range_start, range_end)`` (UTC, end exclusive)."""
    rs = _utc(range_start)
    re = _utc(range_end)
    a = normalize_asset(asset)
    pair = binance_symbol(a)
    return build_exec_frame(
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


def crt_bars_to_records(
    df: pd.DataFrame,
    *,
    asset: str,
    range_start: str | pd.Timestamp,
    range_end: str | pd.Timestamp,
) -> list[dict[str, Any]]:
    """One JSON-serializable dict per exec bar in ``[range_start, range_end)``."""
    rs = _utc(range_start)
    re = _utc(range_end)
    a = normalize_asset(asset)
    out: list[dict[str, Any]] = []
    mask = (df.index >= rs) & (df.index < re)
    sub = df.loc[mask]
    for ts, row in sub.iterrows():
        out.append(
            {
                "kind": "crt_bar",
                "asset": a,
                "timestamp": str(ts),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]) if pd.notna(row.get("volume")) else None,
                "crh": float(row["crh"]) if pd.notna(row.get("crh")) else None,
                "crl": float(row["crl"]) if pd.notna(row.get("crl")) else None,
                "htf_rp_c1": float(row["htf_rp_c1"]) if pd.notna(row.get("htf_rp_c1")) else None,
                "ctx_high": float(row["ctx_high"]) if pd.notna(row.get("ctx_high")) else None,
                "ctx_low": float(row["ctx_low"]) if pd.notna(row.get("ctx_low")) else None,
                "side": str(row.get("side", "SKIP")),
                "reason": str(row.get("reason", "")),
            }
        )
    return out


@dataclass
class WssMonthSimParams:
    """Mirrors key :class:`polymarket_htf.watch_session.SweetSpotWatchParams` fields used at fill."""

    tf_minutes: int = 15
    slug_offset_steps: int = 1
    entry_mode: Literal["until_buffer", "first_minutes"] = "until_buffer"
    entry_end_buffer_sec: float = 90.0
    entry_first_minutes: float = 8.0
    max_gamma_outcome_deviation: float = 0.12
    skip_gamma: bool = True
    require_gamma_active: bool = True
    pullback_frac: float = 0.0008
    fib_lo: float = 0.618
    fib_hi: float = 0.786


def _spot_step_seconds(index: pd.DatetimeIndex, *, default: int = 60) -> int:
    """Median bar spacing in seconds (60 for 1m, 900 for 15m, …)."""
    idx = index.sort_values()
    if len(idx) < 2:
        return default
    deltas = [max(1, int((idx[i + 1] - idx[i]).total_seconds())) for i in range(len(idx) - 1)]
    if not deltas:
        return default
    return int(max(60, round(median(deltas))))


def _entry_window_ok(*, now: float, T: float, T_end: float, p: WssMonthSimParams) -> bool:
    if now < T or now >= T_end - p.entry_end_buffer_sec:
        return False
    if p.entry_mode == "first_minutes":
        if now > T + p.entry_first_minutes * 60.0:
            return False
    return True


def _signal_dict_from_row(ts: pd.Timestamp, row: pd.Series) -> dict[str, Any]:
    return {
        "timestamp": str(ts),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "ctx_high": float(row["ctx_high"]),
        "ctx_low": float(row["ctx_low"]),
        "side": str(row["side"]),
    }


def simulate_wss_window(
    *,
    asset: str,
    sig: dict[str, Any],
    spot_window: pd.DataFrame,
    p: WssMonthSimParams,
) -> dict[str, Any]:
    """
    Replay one arm window using **close** prices as a Chainlink spot proxy.

    ``spot_window`` is usually **1m** Binance bars (``open`` time index, ``now`` = open + 1m) or
    **15m** CRT bars (``now`` = open + 15m) when Binance is unavailable (``--wss-spot-source crt_15m``).
    """
    tfm = exec_interval_to_polymarket_tf_minutes("15m")
    if tfm is None or tfm != p.tf_minutes:
        raise ValueError("simulate_wss_window expects 15m Polymarket windows (tf_minutes=15).")
    ts_bar = pd.Timestamp(sig["timestamp"])
    if ts_bar.tzinfo is None:
        ts_bar = ts_bar.tz_localize("UTC")
    else:
        ts_bar = ts_bar.tz_convert("UTC")

    ch = float(sig["ctx_high"])
    cl = float(sig["ctx_low"])
    close = float(sig["close"])
    side = str(sig["side"])
    if side not in ("UP", "DOWN"):
        return {"result": "not_armable", "reason": "side_not_up_down"}

    trend_up = close >= (ch + cl) / 2.0
    zone = fib_pullback_zone(ch, cl, trend_up, fib_lo=p.fib_lo, fib_hi=p.fib_hi)
    next_wo = next_monitor_window_open_epoch(
        bar_open_utc=ts_bar,
        tf_minutes=p.tf_minutes,
        slug_offset_steps=p.slug_offset_steps,
    )
    T = float(next_wo)
    T_end = T + float(p.tf_minutes * 60)
    slug = build_updown_slug(
        normalize_asset(asset), tf_minutes=p.tf_minutes, window_open_ts=int(next_wo)
    )

    base: dict[str, Any] = {
        "kind": "wss_sim",
        "asset": normalize_asset(asset),
        "arm_bar_ts": str(ts_bar),
        "side": side,
        "slug": slug,
        "T": int(T),
        "T_end": int(T_end),
        "fib_zone": list(zone),
        "trend_up": trend_up,
    }

    if spot_window.empty:
        return {**base, "result": "no_spot_data"}

    step_sec = _spot_step_seconds(spot_window.index)
    session_hi: float | None = None
    session_lo: float | None = None
    pullback_ok = False

    for idx, row in spot_window.sort_index().iterrows():
        spot = float(row["close"])
        now_sec = float((idx + pd.Timedelta(seconds=step_sec)).timestamp())
        if now_sec < T:
            continue
        if now_sec >= T_end:
            return {**base, "result": "timeout"}

        if session_hi is None:
            session_hi = spot
            session_lo = spot
        else:
            session_hi = max(session_hi, spot)
            session_lo = min(session_lo, spot)

        if side == "UP" and session_hi is not None:
            if spot <= session_hi * (1.0 - p.pullback_frac):
                pullback_ok = True
        elif side == "DOWN" and session_lo is not None:
            if spot >= session_lo * (1.0 + p.pullback_frac):
                pullback_ok = True

        if not _entry_window_ok(now=now_sec, T=T, T_end=T_end, p=p):
            continue

        if not p.skip_gamma:
            ev = fetch_event_by_slug(slug)
            if ev is None:
                return {**base, "result": "skip", "reason": "gamma_404"}
            if p.require_gamma_active and (not ev.get("active") or ev.get("closed")):
                return {**base, "result": "skip", "reason": "gamma_inactive"}
            dev = gamma_outcome_sum_deviation(ev)
            if dev is None or dev > p.max_gamma_outcome_deviation:
                continue

        if not pullback_ok:
            continue
        if not spot_in_fib_zone(spot, side, zone):
            continue

        return {
            **base,
            "result": "paper_fill",
            "fill_ts": pd.Timestamp(now_sec, unit="s", tz="UTC").isoformat(),
            "spot": spot,
        }

    return {**base, "result": "timeout"}


def prefetch_binance_1m_range(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Binance **spot** 1m klines ``[start, end)`` UTC (end exclusive)."""
    return fetch_binance_klines_range(symbol.upper(), "1m", start, end)


def simulate_wss_for_crt_frame(
    df: pd.DataFrame,
    *,
    asset: str,
    range_start: str | pd.Timestamp,
    range_end: str | pd.Timestamp,
    spot_bars: pd.DataFrame,
    sim_p: WssMonthSimParams,
) -> list[dict[str, Any]]:
    """
    For each UP/DOWN bar in range, slice ``spot_bars`` to ``[T, T_end)`` and run
    :func:`simulate_wss_window`.
    """
    rs = _utc(range_start)
    re = _utc(range_end)
    a = normalize_asset(asset)
    mask = (df.index >= rs) & (df.index < re)
    sub = df.loc[mask]
    out: list[dict[str, Any]] = []
    for ts, row in sub.iterrows():
        side = str(row.get("side", "SKIP"))
        if side not in ("UP", "DOWN"):
            continue
        sig = _signal_dict_from_row(ts, row)
        next_wo = next_monitor_window_open_epoch(
            bar_open_utc=ts,
            tf_minutes=sim_p.tf_minutes,
            slug_offset_steps=sim_p.slug_offset_steps,
        )
        T = float(next_wo)
        T_end = T + float(sim_p.tf_minutes * 60)
        t0 = pd.Timestamp(T, unit="s", tz="UTC")
        t1 = pd.Timestamp(T_end, unit="s", tz="UTC")
        win = spot_bars[(spot_bars.index >= t0) & (spot_bars.index < t1)]
        out.append(simulate_wss_window(asset=a, sig=sig, spot_window=win, p=sim_p))
    return out


def attach_signals_to_frame(df: pd.DataFrame, *, params: CRTParams) -> pd.DataFrame:
    """Mutate copy with ``side`` / ``reason`` columns via :func:`crt_signal_row`."""
    out = df.copy()
    sides: list[str] = []
    reasons: list[str] = []
    for _, row in out.iterrows():
        s, r = crt_signal_row(row, params=params)
        sides.append(s)
        reasons.append(r)
    out["side"] = sides
    out["reason"] = reasons
    return out
