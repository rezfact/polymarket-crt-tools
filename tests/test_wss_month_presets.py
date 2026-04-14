from __future__ import annotations

from polymarket_htf.crt_wss_monthly import WssMonthSimParams
from polymarket_htf.wss_month_presets import apply_wss_month_preset


def test_wss_preset_default_identity() -> None:
    p0 = WssMonthSimParams()
    assert apply_wss_month_preset(p0, "default") is p0


def test_wss_preset_coarse_spot_relaxes_gates() -> None:
    p0 = WssMonthSimParams(
        pullback_frac=0.0008,
        fib_lo=0.618,
        fib_hi=0.786,
        entry_end_buffer_sec=90.0,
        entry_first_minutes=8.0,
    )
    p1 = apply_wss_month_preset(p0, "coarse_spot")
    assert p1.pullback_frac <= 0.00015
    assert p1.fib_lo <= 0.55
    assert p1.fib_hi >= 0.82
    assert p1.entry_end_buffer_sec <= 45.0
    assert p1.entry_first_minutes >= 12.0
