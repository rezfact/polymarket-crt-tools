"""
Optional **CRT parameter bundles** to reduce mechanical SKIPs (research / Polymarket grids).

``crt_no_distribution_inside`` often dominates when C3 barely misses a strict inside close, or when
the HTF location filter vetoes an otherwise valid AMD. Presets widen those gates in a controlled way.
"""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polymarket_htf.crt_strategy import CRTParams


def apply_crt_preset(params: "CRTParams", preset: str) -> "CRTParams":
    """
    Return a copy of ``params`` with a named preset applied **on top**.

    - ``default`` / empty: unchanged.
    - ``loose``: turn **off** HTF location filter; ``prefer_bull`` on sweep conflicts; slightly
      wider C3 inside-C1 band; allow slightly tighter Candle-1 ranges.
    - ``loose_htf``: keep HTF on but **widen** bull/bear bands; ``prefer_bull`` on conflicts;
      modest distribution buffer; slightly looser min Candle-1 range.
    - ``loose_plus``: same as ``loose`` but **wider** C3 inside-C1 buffer (``>= 0.022``) to shave
      more ``crt_no_distribution_inside`` SKIPs (research).
    """
    p = (preset or "default").strip().lower()
    if p in ("", "default", "none"):
        return params
    if p == "loose":
        return replace(
            params,
            use_htf_location_filter=False,
            sweep_conflict_resolve="prefer_bull",
            distribution_inside_buffer_frac=max(float(params.distribution_inside_buffer_frac), 0.015),
            min_candle1_range_pct=min(float(params.min_candle1_range_pct), 0.0001),
        )
    if p == "loose_htf":
        return replace(
            params,
            use_htf_location_filter=True,
            htf_discount_max=max(float(params.htf_discount_max), 0.48),
            htf_premium_min=min(float(params.htf_premium_min), 0.52),
            sweep_conflict_resolve="prefer_bull",
            distribution_inside_buffer_frac=max(float(params.distribution_inside_buffer_frac), 0.012),
            min_candle1_range_pct=min(float(params.min_candle1_range_pct), 0.0001),
        )
    if p == "loose_plus":
        return replace(
            params,
            use_htf_location_filter=False,
            sweep_conflict_resolve="prefer_bull",
            distribution_inside_buffer_frac=max(float(params.distribution_inside_buffer_frac), 0.022),
            min_candle1_range_pct=min(float(params.min_candle1_range_pct), 0.0001),
        )
    raise ValueError(f"unknown CRT preset {preset!r} (expected default, loose, loose_htf, loose_plus)")
