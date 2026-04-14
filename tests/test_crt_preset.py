from __future__ import annotations

from polymarket_htf.crt_presets import apply_crt_preset
from polymarket_htf.crt_strategy import CRTParams


def test_preset_loose_disables_htf_and_widens_distribution() -> None:
    p0 = CRTParams()
    p1 = apply_crt_preset(p0, "loose")
    assert p1.use_htf_location_filter is False
    assert p1.sweep_conflict_resolve == "prefer_bull"
    assert p1.distribution_inside_buffer_frac >= 0.015
    assert p1.min_candle1_range_pct <= 0.0001


def test_preset_loose_htf_widens_htf_bands() -> None:
    p0 = CRTParams()
    p1 = apply_crt_preset(p0, "loose_htf")
    assert p1.use_htf_location_filter is True
    assert p1.htf_discount_max >= 0.48
    assert p1.htf_premium_min <= 0.52


def test_preset_loose_plus_wider_distribution_buffer() -> None:
    p0 = CRTParams()
    p1 = apply_crt_preset(p0, "loose_plus")
    assert p1.use_htf_location_filter is False
    assert p1.sweep_conflict_resolve == "prefer_bull"
    assert p1.distribution_inside_buffer_frac >= 0.022


def test_preset_default_is_identity() -> None:
    p0 = CRTParams()
    assert apply_crt_preset(p0, "default") is p0
    assert apply_crt_preset(p0, "") is p0
