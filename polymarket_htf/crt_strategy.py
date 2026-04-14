"""
Mechanical **3-candle CRT (Candle Range Theory)** aligned with the AMD / Turtle Soup idea:

**Candle 1 (definition / accumulation):** sets **CRH** (range high) and **CRL** (range low).

**Candle 2 (manipulation):** liquidity grab — wick/body takes price **outside** Candle 1:
  - *Bullish setup:* ``low_2 < CRL`` (sweep sell-side / below Candle 1 low).
  - *Bearish setup:* ``high_2 > CRH`` (sweep buy-side / above Candle 1 high).

**Candle 3 (distribution):** closes **back inside** Candle 1's range
  (``CRL < close_3 < CRH``), implying continuation toward the **opposite** range extreme
  (UP → bias toward CRH; DOWN → bias toward CRL).

Optional **HTF location** filter: bullish CRT only when Candle 1's close sits in the **lower**
part of a rolling higher-timeframe range (support proxy); bearish when in the **upper** part
(resistance proxy). Session / CHOCH / MSS are **not** modeled (needs finer data or discretion).

Outputs ``UP``, ``DOWN``, or ``SKIP`` plus a short reason string.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

SweepConflictResolve = Literal["skip", "prefer_bull", "prefer_bear"]

import numpy as np
import pandas as pd

from polymarket_htf.assets import binance_symbol, normalize_asset, pyth_tv_symbol_for_binance_pair
from polymarket_htf.data import Interval, fetch_binance_klines, fetch_binance_klines_range, interval_duration_seconds


@dataclass
class CRTParams:
    exec_interval: Interval = "15m"
    context_interval: Interval = "1h"
    range_lookback: int = 24
    # HTF “support / resistance” zone for Candle 1 close (0 = at CRL, 1 = at CRH of HTF band).
    htf_discount_max: float = 0.42
    htf_premium_min: float = 0.58
    use_htf_location_filter: bool = True
    # Ignore tiny Candle-1 ranges: (CRH - CRL) / mid_price < this → SKIP.
    min_candle1_range_pct: float = 0.0002
    # Optional: require Candle 3 volume above MA × mult (off by default).
    vol_ma: int = 20
    vol_mult: float = 1.0
    require_volume_confirm: bool = False
    # When Candle-2 sweeps **both** sides of Candle-1: default SKIP; optional tie-break for looser backtests.
    sweep_conflict_resolve: SweepConflictResolve = "skip"
    # Widen Candle-3 "inside C1" test by ``buffer_frac * (CRH-CRL)`` on each side (0 = strict CRT).
    distribution_inside_buffer_frac: float = 0.0


def _range_position(close: float, rh: float, rl: float) -> float:
    span = rh - rl
    if span <= 0 or not np.isfinite(span):
        return 0.5
    return float(np.clip((close - rl) / span, 0.0, 1.0))


def attach_crt_features(
    exec_df: pd.DataFrame,
    ctx_high: pd.Series,
    ctx_low: pd.Series,
    *,
    params: CRTParams,
) -> pd.DataFrame:
    out = exec_df.copy()
    out["ctx_high"] = ctx_high.reindex(out.index, method="ffill")
    out["ctx_low"] = ctx_low.reindex(out.index, method="ffill")

    # Candle 1 = two bars back; Candle 2 = one bar back; Candle 3 = current bar (signal at close).
    out["crh"] = out["high"].shift(2)
    out["crl"] = out["low"].shift(2)
    out["c1_close"] = out["close"].shift(2)
    c2_low = out["low"].shift(1)
    c2_high = out["high"].shift(1)
    out["sweep_below_crl"] = c2_low < out["crl"]
    out["sweep_above_crh"] = c2_high > out["crh"]
    span_c1 = out["crh"] - out["crl"]
    buf = span_c1 * float(params.distribution_inside_buffer_frac)
    buf = buf.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    lo_in = out["crl"] - buf
    hi_in = out["crh"] + buf
    out["c3_inside_c1"] = (out["close"] > lo_in) & (out["close"] < hi_in)
    out["sweep_conflict"] = out["sweep_below_crl"] & out["sweep_above_crh"]

    mid_c1 = (out["crh"] + out["crl"]) / 2.0
    out["c1_range_pct"] = span_c1 / mid_c1.replace(0, np.nan)

    out["htf_rp_c1"] = [
        _range_position(c, h, l)
        for c, h, l in zip(out["c1_close"], out["ctx_high"], out["ctx_low"])
    ]

    out["vol_ma"] = out["volume"].rolling(params.vol_ma, min_periods=params.vol_ma).mean()
    out["vol_confirm"] = out["volume"] > (out["vol_ma"] * params.vol_mult)
    return out


def crt_signal_row(row: pd.Series, *, params: CRTParams) -> tuple[str, str]:
    need = (
        "crh",
        "crl",
        "c1_close",
        "sweep_below_crl",
        "sweep_above_crh",
        "c3_inside_c1",
        "sweep_conflict",
        "c1_range_pct",
        "htf_rp_c1",
        "ctx_high",
        "ctx_low",
    )
    if any(pd.isna(row.get(k)) for k in need):
        return "SKIP", "warmup"

    if params.require_volume_confirm:
        if pd.isna(row.get("vol_ma")) or pd.isna(row.get("vol_confirm")):
            return "SKIP", "warmup_vol"
        if not bool(row["vol_confirm"]):
            return "SKIP", "crt_no_volume_confirm"

    crh = float(row["crh"])
    crl = float(row["crl"])
    mid = (crh + crl) / 2.0
    if mid <= 0 or not np.isfinite(mid):
        return "SKIP", "bad_range_mid"
    span = crh - crl
    rng_pct = span / mid
    if not np.isfinite(rng_pct) or rng_pct < params.min_candle1_range_pct:
        return "SKIP", "c1_range_too_tight"

    sweep_below = bool(row["sweep_below_crl"])
    sweep_above = bool(row["sweep_above_crh"])
    inside = bool(row["c3_inside_c1"])
    if bool(row["sweep_conflict"]):
        if params.sweep_conflict_resolve == "skip":
            return "SKIP", "crt_sweep_conflict"
        if params.sweep_conflict_resolve == "prefer_bull":
            sweep_above = False
        elif params.sweep_conflict_resolve == "prefer_bear":
            sweep_below = False
        else:
            return "SKIP", "crt_sweep_conflict"
    htf_rp = float(row["htf_rp_c1"])

    bull = sweep_below and inside and not sweep_above
    bear = sweep_above and inside and not sweep_below

    if params.use_htf_location_filter:
        bull = bull and htf_rp <= params.htf_discount_max
        bear = bear and htf_rp >= params.htf_premium_min

    if bull:
        return "UP", "crt_amd_bull_sweep_crl_c3_inside"
    if bear:
        return "DOWN", "crt_amd_bear_sweep_crh_c3_inside"
    if sweep_below or sweep_above:
        return "SKIP", "crt_no_distribution_inside"
    return "SKIP", "crt_no_manipulation"


def _utc(ts: pd.Timestamp | str) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.tz_localize("UTC")
    return t.tz_convert("UTC")


def build_exec_frame(
    *,
    binance_pair: str,
    params: CRTParams,
    range_start: pd.Timestamp | str | None = None,
    range_end: pd.Timestamp | str | None = None,
    warmup_days: float = 45.0,
    use_binance_vision: bool = False,
    vision_cache_dir: Path | str | None = None,
    vision_origin: str | None = None,
    price_source: Literal["binance", "pyth"] = "pyth",
) -> pd.DataFrame:
    if use_binance_vision and price_source == "pyth":
        raise ValueError("use_binance_vision and price_source='pyth' are mutually exclusive")
    if range_start is not None and range_end is not None:
        rs = _utc(range_start)
        re = _utc(range_end)
        warm = rs - pd.Timedelta(days=float(warmup_days))
        if use_binance_vision:
            from polymarket_htf.binance_vision import load_spot_klines_range_from_vision

            vdir = Path(vision_cache_dir) if vision_cache_dir else Path("data/binance_vision")
            exec_df = load_spot_klines_range_from_vision(
                binance_pair,
                params.exec_interval,
                warm,
                re,
                cache_dir=vdir,
                vision_origin=vision_origin,
            )
            ctx = load_spot_klines_range_from_vision(
                binance_pair,
                params.context_interval,
                warm,
                re,
                cache_dir=vdir,
                vision_origin=vision_origin,
            )
        elif price_source == "pyth":
            from polymarket_htf import pyth_prices

            pyth_sym = pyth_tv_symbol_for_binance_pair(binance_pair)
            exec_df = pyth_prices.fetch_pyth_klines_range(
                params.exec_interval,  # type: ignore[arg-type]
                symbol=pyth_sym,
                since=warm,
                until=re,
            )
            ctx = pyth_prices.fetch_pyth_klines_range(
                params.context_interval,  # type: ignore[arg-type]
                symbol=pyth_sym,
                since=warm,
                until=re,
            )
        else:
            exec_df = fetch_binance_klines_range(binance_pair, params.exec_interval, warm, re)
            ctx = fetch_binance_klines_range(binance_pair, params.context_interval, warm, re)
    elif price_source == "pyth":
        from polymarket_htf import pyth_prices

        pyth_sym = pyth_tv_symbol_for_binance_pair(binance_pair)
        # Live path: keep Pyth TV ``from``/``to`` span modest (large spans often **500** or timeout).
        exec_limit = 220
        exec_df = pyth_prices.fetch_pyth_klines(params.exec_interval, symbol=pyth_sym, limit=exec_limit)  # type: ignore[arg-type]
        exec_sec = float(interval_duration_seconds(params.exec_interval))
        ctx_sec = float(interval_duration_seconds(params.context_interval))
        ctx_bars = int((exec_limit * exec_sec) / ctx_sec) + int(params.range_lookback) + 48
        ctx_limit = int(min(200, max(80, ctx_bars)))
        ctx = pyth_prices.fetch_pyth_klines(params.context_interval, symbol=pyth_sym, limit=ctx_limit)  # type: ignore[arg-type]
    else:
        exec_df = fetch_binance_klines(binance_pair, params.exec_interval, limit=500)
        ctx = fetch_binance_klines(binance_pair, params.context_interval, limit=500)
    ctx_high = ctx["high"].rolling(params.range_lookback, min_periods=max(5, params.range_lookback // 4)).max()
    ctx_low = ctx["low"].rolling(params.range_lookback, min_periods=max(5, params.range_lookback // 4)).min()
    ctx_high_x = ctx_high.reindex(exec_df.index, method="ffill")
    ctx_low_x = ctx_low.reindex(exec_df.index, method="ffill")
    return attach_crt_features(exec_df, ctx_high_x, ctx_low_x, params=params)


def strip_incomplete_exec_tail(
    df: pd.DataFrame,
    exec_interval: str,
    *,
    slack_sec: float = 2.0,
    now_ts: float | None = None,
) -> pd.DataFrame:
    """Drop the last row if its exec bar has not **closed** yet in wall-clock time."""
    import time

    if df.empty:
        return df
    now = time.time() if now_ts is None else float(now_ts)
    sec = float(interval_duration_seconds(exec_interval))
    last_open = df.index[-1]
    t0 = float(pd.Timestamp(last_open).timestamp())
    if t0 + sec > now + float(slack_sec):
        return df.iloc[:-1].copy()
    return df.copy()


def last_signal_for_asset(
    asset: str,
    *,
    params: CRTParams | None = None,
    price_source: Literal["binance", "pyth"] = "pyth",
) -> dict:
    params = params or CRTParams()
    sym = binance_symbol(normalize_asset(asset))
    df = build_exec_frame(binance_pair=sym, params=params, price_source=price_source)
    sides: list[str] = []
    reasons: list[str] = []
    for _, row in df.iterrows():
        s, r = crt_signal_row(row, params=params)
        sides.append(s)
        reasons.append(r)
    df["side"] = sides
    df["reason"] = reasons
    last = df.iloc[-1]
    return {
        "timestamp": str(last.name),
        "open": float(last["open"]),
        "high": float(last["high"]),
        "low": float(last["low"]),
        "close": float(last["close"]),
        "crh": float(last["crh"]) if pd.notna(last.get("crh")) else None,
        "crl": float(last["crl"]) if pd.notna(last.get("crl")) else None,
        "htf_rp_c1": float(last["htf_rp_c1"]) if pd.notna(last.get("htf_rp_c1")) else None,
        "side": last["side"],
        "reason": last["reason"],
    }


def last_signal_completed_bar(
    asset: str,
    *,
    params: CRTParams | None = None,
    price_source: Literal["binance", "pyth"] = "pyth",
    now_ts: float | None = None,
) -> dict[str, Any]:
    """
    Same as :func:`last_signal_for_asset` but uses the **last fully closed** exec bar
    (drops an in-progress candle for live / polling loops).
    """
    params = params or CRTParams()
    sym = binance_symbol(normalize_asset(asset))
    df0 = build_exec_frame(binance_pair=sym, params=params, price_source=price_source)
    df = strip_incomplete_exec_tail(df0, str(params.exec_interval), now_ts=now_ts)
    if df.empty:
        return {
            "timestamp": None,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "crh": None,
            "crl": None,
            "htf_rp_c1": None,
            "ctx_high": None,
            "ctx_low": None,
            "side": "SKIP",
            "reason": "no_closed_bar",
        }
    sides: list[str] = []
    reasons: list[str] = []
    for _, row in df.iterrows():
        s, r = crt_signal_row(row, params=params)
        sides.append(s)
        reasons.append(r)
    df = df.copy()
    df["side"] = sides
    df["reason"] = reasons
    last = df.iloc[-1]
    return {
        "timestamp": str(last.name),
        "open": float(last["open"]),
        "high": float(last["high"]),
        "low": float(last["low"]),
        "close": float(last["close"]),
        "crh": float(last["crh"]) if pd.notna(last.get("crh")) else None,
        "crl": float(last["crl"]) if pd.notna(last.get("crl")) else None,
        "htf_rp_c1": float(last["htf_rp_c1"]) if pd.notna(last.get("htf_rp_c1")) else None,
        "ctx_high": float(last["ctx_high"]) if pd.notna(last.get("ctx_high")) else None,
        "ctx_low": float(last["ctx_low"]) if pd.notna(last.get("ctx_low")) else None,
        "side": last["side"],
        "reason": last["reason"],
    }
