from __future__ import annotations

from polymarket_htf.watch_session import SweetSpotWatchParams
from polymarket_htf.wss_watch_presets import apply_sweet_spot_watch_preset


def test_sweet_spot_watch_preset_default_identity() -> None:
    p0 = SweetSpotWatchParams()
    assert apply_sweet_spot_watch_preset(p0, "default") is p0


def test_sweet_spot_watch_preset_late_window() -> None:
    p0 = SweetSpotWatchParams()
    p1 = apply_sweet_spot_watch_preset(p0, "late_window")
    assert p1.late_fill_min_elapsed_sec == 600.0


def test_sweet_spot_watch_preset_late_window_quality() -> None:
    p0 = SweetSpotWatchParams()
    p1 = apply_sweet_spot_watch_preset(p0, "late_window_quality")
    assert p1.late_fill_min_elapsed_sec == 600.0
    assert p1.max_retrace_frac == 0.0009


def test_sweet_spot_watch_preset_continuation() -> None:
    p0 = SweetSpotWatchParams(
        pullback_frac=0.0008,
        entry_end_buffer_sec=90.0,
        entry_first_minutes=8.0,
        max_gamma_outcome_deviation=0.12,
    )
    p1 = apply_sweet_spot_watch_preset(p0, "continuation")
    assert p1.pullback_frac <= 0.00055
    assert p1.entry_end_buffer_sec <= 55.0
    assert p1.entry_first_minutes >= 14.0
    assert p1.max_gamma_outcome_deviation >= 0.14
