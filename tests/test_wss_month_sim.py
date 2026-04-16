from __future__ import annotations

import pandas as pd

from polymarket_htf.crt_wss_monthly import WssMonthSimParams, late_fill_timing_ok, simulate_wss_window
from polymarket_htf.gamma import next_monitor_window_open_epoch


def test_simulate_wss_paper_fill_up_after_pullback() -> None:
    """Synthetic 1m path: session high then pullback by ``pullback_frac`` → paper_fill."""
    ts_bar = pd.Timestamp("2026-01-01 12:00:00+00:00")
    sig = {
        "timestamp": str(ts_bar),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "ctx_high": 110.0,
        "ctx_low": 90.0,
        "side": "UP",
    }
    # trend_up True (100 >= 100); pullback from session high unlocks fill.
    wo = next_monitor_window_open_epoch(bar_open_utc=ts_bar, tf_minutes=15, slug_offset_steps=1)
    T0 = pd.Timestamp(float(wo), unit="s", tz="UTC")
    idx = pd.date_range(T0, periods=8, freq="1min", tz="UTC")
    closes = [100.0, 100.0, 99.85, 99.7, 96.5, 96.4, 96.3, 96.2]
    m1 = pd.DataFrame({"close": closes}, index=idx)
    p = WssMonthSimParams(
        tf_minutes=15,
        slug_offset_steps=1,
        entry_end_buffer_sec=30.0,
        pullback_frac=0.0008,
        skip_gamma=True,
    )
    out = simulate_wss_window(asset="btc", sig=sig, spot_window=m1, p=p)
    assert out["result"] == "paper_fill"
    assert out["side"] == "UP"
    assert "fill_ts" in out
    assert out.get("settlement_tie") is False
    assert out.get("underlying_up") is False
    assert out.get("side_win") is False
    assert float(out["spot_window_open"]) == 100.0
    assert float(out["spot_window_settle"]) == 96.2


def test_simulate_wss_nearmiss_on_timeout() -> None:
    """With track_nearmiss, timeout rows include nm_* path aggregates."""
    ts_bar = pd.Timestamp("2026-01-01 12:00:00+00:00")
    sig = {
        "timestamp": str(ts_bar),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "ctx_high": 110.0,
        "ctx_low": 90.0,
        "side": "UP",
    }
    wo = next_monitor_window_open_epoch(bar_open_utc=ts_bar, tf_minutes=15, slug_offset_steps=1)
    T0 = pd.Timestamp(float(wo), unit="s", tz="UTC")
    idx = pd.date_range(T0, periods=5, freq="1min", tz="UTC")
    # Stay flat near 100: no pullback from session high → timeout
    closes = [100.0, 100.0, 100.0, 100.0, 100.0]
    m1 = pd.DataFrame({"close": closes}, index=idx)
    p = WssMonthSimParams(
        tf_minutes=15,
        slug_offset_steps=1,
        entry_end_buffer_sec=30.0,
        pullback_frac=0.0008,
        skip_gamma=True,
        track_nearmiss=True,
    )
    out = simulate_wss_window(asset="btc", sig=sig, spot_window=m1, p=p)
    assert out["result"] == "timeout"
    assert out.get("nm_ever_pullback_ok") is False
    assert out.get("nm_last_pullback_ok") is False
    assert "nm_max_retrace_frac" in out
    assert float(out.get("nm_max_retrace_frac") or 0) == 0.0
    assert int(out.get("nm_steps_in_window") or 0) >= 1


def test_simulate_wss_post_window_spot_after_T_end() -> None:
    """Optional post-window Binance closes attached on paper_fill."""
    ts_bar = pd.Timestamp("2026-01-01 12:00:00+00:00")
    sig = {
        "timestamp": str(ts_bar),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "ctx_high": 110.0,
        "ctx_low": 90.0,
        "side": "UP",
    }
    wo = next_monitor_window_open_epoch(bar_open_utc=ts_bar, tf_minutes=15, slug_offset_steps=1)
    T0 = pd.Timestamp(float(wo), unit="s", tz="UTC")
    T_end = float(wo) + 15 * 60
    te = pd.Timestamp(T_end, unit="s", tz="UTC")
    idx_in = pd.date_range(T0, periods=8, freq="1min", tz="UTC")
    closes_in = [100.0, 100.0, 99.85, 99.7, 96.5, 96.4, 96.3, 96.2]
    idx_post = pd.date_range(te, periods=2, freq="1min", tz="UTC")
    closes_post = [95.5, 94.5]
    spot_all = pd.concat(
        [
            pd.DataFrame({"close": closes_in}, index=idx_in),
            pd.DataFrame({"close": closes_post}, index=idx_post),
        ]
    )
    win = spot_all[(spot_all.index >= T0) & (spot_all.index < te)]
    p = WssMonthSimParams(
        tf_minutes=15,
        slug_offset_steps=1,
        entry_end_buffer_sec=30.0,
        pullback_frac=0.0008,
        skip_gamma=True,
        post_spot_sec=120.0,
    )
    out = simulate_wss_window(asset="btc", sig=sig, spot_window=win, spot_all=spot_all, p=p)
    assert out["result"] == "paper_fill"
    assert out.get("post_T_end_first_close") == 95.5
    assert out.get("post_T_end_last_close") == 94.5
    assert abs(float(out["underlying_change_after_window"]) - (94.5 - 96.2)) < 1e-9


def test_late_fill_timing_ok() -> None:
    T, T_end = 1000.0, 1900.0
    assert late_fill_timing_ok(now=1200.0, T=T, T_end=T_end, min_elapsed=None, max_remaining=None)
    assert not late_fill_timing_ok(now=1200.0, T=T, T_end=T_end, min_elapsed=250.0, max_remaining=None)
    assert late_fill_timing_ok(now=1300.0, T=T, T_end=T_end, min_elapsed=250.0, max_remaining=None)
    assert not late_fill_timing_ok(now=1300.0, T=T, T_end=T_end, min_elapsed=None, max_remaining=500.0)
    assert late_fill_timing_ok(now=1500.0, T=T, T_end=T_end, min_elapsed=None, max_remaining=500.0)


def test_simulate_wss_late_min_elapsed_blocks_fill_until_late() -> None:
    """With high min_elapsed, first pullback moment is too early → timeout."""
    ts_bar = pd.Timestamp("2026-01-01 12:00:00+00:00")
    sig = {
        "timestamp": str(ts_bar),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "ctx_high": 110.0,
        "ctx_low": 90.0,
        "side": "UP",
    }
    wo = next_monitor_window_open_epoch(bar_open_utc=ts_bar, tf_minutes=15, slug_offset_steps=1)
    T0 = pd.Timestamp(float(wo), unit="s", tz="UTC")
    idx = pd.date_range(T0, periods=8, freq="1min", tz="UTC")
    closes = [100.0, 100.0, 99.85, 99.7, 96.5, 96.4, 96.3, 96.2]
    m1 = pd.DataFrame({"close": closes}, index=idx)
    p = WssMonthSimParams(
        tf_minutes=15,
        slug_offset_steps=1,
        entry_end_buffer_sec=30.0,
        pullback_frac=0.0008,
        skip_gamma=True,
        late_fill_min_elapsed_sec=99999.0,
    )
    out = simulate_wss_window(asset="btc", sig=sig, spot_window=m1, p=p)
    assert out["result"] == "timeout"


def test_simulate_wss_max_retrace_blocks_chase_fill() -> None:
    """With max_retrace_frac set, overextended late retrace should timeout."""
    ts_bar = pd.Timestamp("2026-01-01 12:00:00+00:00")
    sig = {
        "timestamp": str(ts_bar),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "ctx_high": 110.0,
        "ctx_low": 90.0,
        "side": "UP",
    }
    wo = next_monitor_window_open_epoch(bar_open_utc=ts_bar, tf_minutes=15, slug_offset_steps=1)
    T0 = pd.Timestamp(float(wo), unit="s", tz="UTC")
    idx = pd.date_range(T0, periods=8, freq="1min", tz="UTC")
    closes = [100.0, 100.0, 99.85, 99.7, 96.5, 96.4, 96.3, 96.2]
    m1 = pd.DataFrame({"close": closes}, index=idx)
    p = WssMonthSimParams(
        tf_minutes=15,
        slug_offset_steps=1,
        entry_end_buffer_sec=30.0,
        pullback_frac=0.0008,
        max_retrace_frac=0.0009,
        skip_gamma=True,
    )
    out = simulate_wss_window(asset="btc", sig=sig, spot_window=m1, p=p)
    assert out["result"] == "timeout"


def test_simulate_wss_no_1m() -> None:
    sig = {
        "timestamp": "2026-01-01 12:00:00+00:00",
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.0,
        "ctx_high": 1.2,
        "ctx_low": 0.8,
        "side": "UP",
    }
    out = simulate_wss_window(asset="btc", sig=sig, spot_window=pd.DataFrame(), p=WssMonthSimParams())
    assert out["result"] == "no_spot_data"
