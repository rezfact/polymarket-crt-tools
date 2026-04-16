from __future__ import annotations

from polymarket_htf.crt_wss_monthly import WssMonthSimParams
from polymarket_htf.wss_month_presets import apply_wss_month_preset


def test_wss_preset_default_identity() -> None:
    p0 = WssMonthSimParams()
    assert apply_wss_month_preset(p0, "default") is p0


def test_wss_preset_coarse_spot_relaxes_gates() -> None:
    p0 = WssMonthSimParams(
        pullback_frac=0.0008,
        entry_end_buffer_sec=90.0,
        entry_first_minutes=8.0,
    )
    p1 = apply_wss_month_preset(p0, "coarse_spot")
    assert p1.pullback_frac <= 0.00015
    assert p1.entry_end_buffer_sec <= 45.0
    assert p1.entry_first_minutes >= 12.0


def test_wss_preset_late_window_min_elapsed() -> None:
    p0 = WssMonthSimParams()
    p1 = apply_wss_month_preset(p0, "late_window")
    assert p1.late_fill_min_elapsed_sec == 600.0


def test_wss_preset_late_window_quality() -> None:
    p0 = WssMonthSimParams()
    p1 = apply_wss_month_preset(p0, "late_window_quality")
    assert p1.late_fill_min_elapsed_sec == 600.0
    assert p1.max_retrace_frac == 0.0009


def test_wss_preset_continuation_relaxes_gates() -> None:
    p0 = WssMonthSimParams(
        pullback_frac=0.0008,
        entry_end_buffer_sec=90.0,
        entry_first_minutes=8.0,
        max_gamma_outcome_deviation=0.12,
    )
    p1 = apply_wss_month_preset(p0, "continuation")
    assert p1.pullback_frac <= 0.00055
    assert p1.entry_end_buffer_sec <= 55.0
    assert p1.entry_first_minutes >= 14.0
    assert p1.max_gamma_outcome_deviation >= 0.14
