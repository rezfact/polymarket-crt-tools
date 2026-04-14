from __future__ import annotations

import pandas as pd

from polymarket_htf.crt_wss_monthly import WssMonthSimParams, simulate_wss_window
from polymarket_htf.gamma import next_monitor_window_open_epoch


def test_simulate_wss_paper_fill_up_after_pullback() -> None:
    """Synthetic 1m path: pullback then fib hit → paper_fill."""
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
    # trend_up True (100 >= 100). Fib zone from (110,90) up-trend.
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
