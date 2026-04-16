"""
Month-range **CRT bar export** + **WSS-style entry simulation** (research / batch).

CRT OHLC uses :func:`polymarket_htf.crt_strategy.build_exec_frame` (Pyth by default, or Binance / Vision).

WSS simulation can use **Binance 1m closes** as a Chainlink **spot proxy** (or ``crt_15m`` / presets) inside each Polymarket
``[T, T_end)`` window (same **pullback + entry-window** rules as :class:`SweetSpotWatchParams`; fill has no fib gate).
Gamma checks are optional (``skip_gamma=True`` avoids HTTP during long runs).

Each ``paper_fill`` row includes a **research** window settlement proxy (first vs last close in the
slice) plus ``side_win``; aggregate WR/PnL via :func:`polymarket_htf.backtest_crt.summarize_wss_sim_fills`.

Optional (month batch): ``post_spot_sec`` adds **Binance 1m** closes strictly **after** ``T_end``;
``gamma_prices_at_fill`` adds **Gamma** outcome mids / side entry at fill time (HTTP per fill).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Any, Literal

import pandas as pd

from polymarket_htf.assets import binance_symbol, normalize_asset
from polymarket_htf.crt_strategy import CRTParams, build_exec_frame, crt_signal_row
from polymarket_htf.data import fetch_binance_klines_range
from polymarket_htf.gamma import (
    build_updown_slug,
    exec_interval_to_polymarket_tf_minutes,
    fetch_event_by_slug,
    gamma_entry_price_for_crt_side,
    gamma_outcome_sum_deviation,
    gamma_yes_no_mids,
    next_monitor_window_open_epoch,
)


def late_fill_timing_ok(
    *,
    now: float,
    T: float,
    T_end: float,
    min_elapsed: float | None,
    max_remaining: float | None,
) -> bool:
    """
    Optional **late window** gates (Polymarket ``T`` = window open epoch seconds).

    - ``min_elapsed``: require ``now - T >= min_elapsed`` (no fill in the first N seconds).
    - ``max_remaining``: require ``T_end - now <= max_remaining`` (only when at most N seconds
      left until window end). Must exceed ``entry_end_buffer_sec`` or no fill is possible.

    When both are set, both must pass. ``None`` disables that constraint.
    """
    if min_elapsed is not None and (now - T) < float(min_elapsed):
        return False
    if max_remaining is not None and (T_end - now) > float(max_remaining):
        return False
    return True


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
    # Optional anti-chase gate: require ``retrace_frac <= max_retrace_frac`` at fill time.
    max_retrace_frac: float | None = None
    # When True, ``simulate_wss_window`` adds ``nm_*`` path stats on ``timeout`` / ``paper_fill`` (local batch tuning).
    track_nearmiss: bool = False
    # After Polymarket ``T_end``, slice ``[T_end, T_end + post_spot_sec)`` from ``spot_all`` for underlying path.
    post_spot_sec: float = 0.0
    # One Gamma fetch per ``paper_fill`` to attach ``gamma_*_at_fill`` (independent of ``skip_gamma`` gate).
    gamma_prices_at_fill: bool = False
    # Late-only fills (see :func:`late_fill_timing_ok`); ``None`` = off (fill anytime in entry window).
    late_fill_min_elapsed_sec: float | None = None
    late_fill_max_remaining_sec: float | None = None


def wss_proxy_settlement_from_slice(spot_window: pd.DataFrame, *, side: str) -> dict[str, Any]:
    """
    Research-only **Polymarket window** proxy using the same spot feed as the WSS sim:

    - ``spot_window_open`` / ``spot_window_settle``: first and last **close** in the ``[T, T_end)``
      slice (Binance 1m proxy or CRT 15m closes).
    - ``underlying_up``: ``settle > open`` (strict). Ties → ``settlement_tie`` and no ``side_win``.
    - ``side_win``: whether the **armed** ``side`` (UP/DOWN) wins that binary.
    """
    w = spot_window.sort_index()
    if w.empty or "close" not in w.columns:
        return {
            "spot_window_open": None,
            "spot_window_settle": None,
            "settlement_tie": False,
            "underlying_up": None,
            "side_win": None,
            "settlement_note": "empty_spot_window",
        }
    o = float(w.iloc[0]["close"])
    s = float(w.iloc[-1]["close"])
    if o == s:
        return {
            "spot_window_open": o,
            "spot_window_settle": s,
            "settlement_tie": True,
            "underlying_up": None,
            "side_win": None,
            "settlement_note": "open_eq_settle",
        }
    underlying_up = s > o
    win = (str(side) == "UP" and underlying_up) or (str(side) == "DOWN" and not underlying_up)
    return {
        "spot_window_open": o,
        "spot_window_settle": s,
        "settlement_tie": False,
        "underlying_up": underlying_up,
        "side_win": win,
        "settlement_note": None,
    }


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


def _post_window_spot_fields(
    *,
    spot_all: pd.DataFrame,
    T_end: float,
    post_spot_sec: float,
    window_settle_close: float | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if post_spot_sec <= 0 or spot_all.empty or "close" not in spot_all.columns:
        return out
    te = pd.Timestamp(T_end, unit="s", tz="UTC")
    te2 = te + pd.Timedelta(seconds=float(post_spot_sec))
    post = spot_all[(spot_all.index >= te) & (spot_all.index < te2)].sort_index()
    if post.empty:
        return out
    oc = float(post.iloc[0]["close"])
    lc = float(post.iloc[-1]["close"])
    out["post_T_end_first_close"] = oc
    out["post_T_end_last_close"] = lc
    out["post_window_sec"] = float(post_spot_sec)
    if window_settle_close is not None and math.isfinite(float(window_settle_close)):
        out["underlying_change_after_window"] = lc - float(window_settle_close)
    return out


def _gamma_prices_at_fill_fields(*, slug: str, side: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        ev = fetch_event_by_slug(slug)
    except Exception as e:  # noqa: BLE001
        out["gamma_prices_at_fill_error"] = f"{type(e).__name__}:{e}"
        return out
    if ev is None:
        out["gamma_prices_at_fill"] = "404"
        return out
    pr = gamma_yes_no_mids(ev)
    if pr:
        out["gamma_yes_mid_at_fill"] = float(pr[0])
        out["gamma_no_mid_at_fill"] = float(pr[1])
    gep = gamma_entry_price_for_crt_side(ev, side)
    if gep is not None:
        out["gamma_entry_mid_at_fill"] = float(gep)
    return out


def _retrace_frac(*, side: str, spot: float, session_hi: float | None, session_lo: float | None) -> float:
    if side == "UP" and session_hi is not None and float(session_hi) > 0:
        return max(0.0, (float(session_hi) - spot) / float(session_hi))
    if side == "DOWN" and session_lo is not None and float(session_lo) > 0:
        return max(0.0, (spot - float(session_lo)) / float(session_lo))
    return 0.0


def simulate_wss_window(
    *,
    asset: str,
    sig: dict[str, Any],
    spot_window: pd.DataFrame,
    p: WssMonthSimParams,
    spot_all: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Replay one arm window using **close** prices as a Chainlink spot proxy.

    ``spot_window`` is usually **1m** Binance bars (``open`` time index, ``now`` = open + 1m) or
    **15m** CRT bars (``now`` = open + 15m) when Binance is unavailable (``--wss-spot-source crt_15m``).

    **Fill rule:** entry window + optional Gamma + ``pullback_ok`` (session extreme retrace by
    ``pullback_frac``) — no fib band.
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
        "trend_up": trend_up,
    }

    if spot_window.empty:
        return {**base, "result": "no_spot_data"}

    step_sec = _spot_step_seconds(spot_window.index)
    session_hi: float | None = None
    session_lo: float | None = None
    pullback_ok = False

    track_nm = bool(p.track_nearmiss)
    nm_ever_pullback_ok = False
    nm_max_retrace_frac = 0.0
    nm_steps_in_window = 0
    nm_last_pullback_ok = False
    nm_last_entry_window_ok = False
    nm_last_retrace_frac = 0.0

    def _nm_dict() -> dict[str, Any]:
        return {
            "nm_ever_pullback_ok": nm_ever_pullback_ok,
            "nm_max_retrace_frac": float(nm_max_retrace_frac),
            "nm_steps_in_window": int(nm_steps_in_window),
            "nm_last_pullback_ok": nm_last_pullback_ok,
            "nm_last_entry_window_ok": nm_last_entry_window_ok,
            "nm_last_retrace_frac": float(nm_last_retrace_frac),
        }

    for idx, row in spot_window.sort_index().iterrows():
        spot = float(row["close"])
        now_sec = float((idx + pd.Timedelta(seconds=step_sec)).timestamp())
        if now_sec < T:
            continue
        if now_sec >= T_end:
            out = {**base, "result": "timeout"}
            if track_nm:
                out.update(_nm_dict())
            return out

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

        entry_ok = _entry_window_ok(now=now_sec, T=T, T_end=T_end, p=p)
        rf = _retrace_frac(side=side, spot=spot, session_hi=session_hi, session_lo=session_lo)
        if track_nm:
            nm_steps_in_window += 1
            nm_ever_pullback_ok = nm_ever_pullback_ok or pullback_ok
            nm_max_retrace_frac = max(nm_max_retrace_frac, rf)
            nm_last_pullback_ok = pullback_ok
            nm_last_entry_window_ok = entry_ok
            nm_last_retrace_frac = rf

        if not entry_ok:
            continue

        if not p.skip_gamma:
            ev = fetch_event_by_slug(slug)
            if ev is None:
                out = {**base, "result": "skip", "reason": "gamma_404"}
                if track_nm:
                    out.update(_nm_dict())
                return out
            if p.require_gamma_active and (not ev.get("active") or ev.get("closed")):
                out = {**base, "result": "skip", "reason": "gamma_inactive"}
                if track_nm:
                    out.update(_nm_dict())
                return out
            dev = gamma_outcome_sum_deviation(ev)
            if dev is None or dev > p.max_gamma_outcome_deviation:
                continue

        if not pullback_ok:
            continue
        if p.max_retrace_frac is not None and rf > float(p.max_retrace_frac):
            continue
        if not late_fill_timing_ok(
            now=now_sec,
            T=T,
            T_end=T_end,
            min_elapsed=p.late_fill_min_elapsed_sec,
            max_remaining=p.late_fill_max_remaining_sec,
        ):
            continue

        settle_extras = wss_proxy_settlement_from_slice(spot_window, side=side)
        out = {
            **base,
            "result": "paper_fill",
            "fill_ts": pd.Timestamp(now_sec, unit="s", tz="UTC").isoformat(),
            "spot": spot,
            "retrace_frac": float(rf),
            **settle_extras,
        }
        if float(p.post_spot_sec) > 0 and spot_all is not None and not spot_all.empty:
            sws = settle_extras.get("spot_window_settle")
            swf: float | None = None
            if sws is not None and pd.notna(sws):
                try:
                    swf = float(sws)
                except (TypeError, ValueError):
                    swf = None
            out.update(
                _post_window_spot_fields(
                    spot_all=spot_all,
                    T_end=T_end,
                    post_spot_sec=float(p.post_spot_sec),
                    window_settle_close=swf,
                )
            )
        if p.gamma_prices_at_fill:
            out.update(_gamma_prices_at_fill_fields(slug=slug, side=side))
        if track_nm:
            out.update(_nm_dict())
        return out

    out = {**base, "result": "timeout"}
    if track_nm:
        out.update(_nm_dict())
    return out


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
        spot_all = spot_bars if float(sim_p.post_spot_sec) > 0 else None
        out.append(simulate_wss_window(asset=a, sig=sig, spot_window=win, p=sim_p, spot_all=spot_all))
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
