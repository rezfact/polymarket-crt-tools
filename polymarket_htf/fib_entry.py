"""
HTF range → Fibonacci **pullback band** (0.618–0.786 style) for sweet-spot checks (E6).

Convention (trend-up): retrace from ``htf_high`` toward ``htf_low``; band is between
``high - fib_hi * R`` and ``high - fib_lo * R`` with ``R = htf_high - htf_low``,
``fib_lo < fib_hi`` (e.g. 0.618 and 0.786).

Trend-down: retrace up from ``htf_low`` toward ``htf_high``; band between
``low + fib_lo * R`` and ``low + fib_hi * R``.
"""
from __future__ import annotations


def fib_pullback_zone(
    htf_high: float,
    htf_low: float,
    trend_up: bool,
    *,
    fib_lo: float = 0.618,
    fib_hi: float = 0.786,
) -> tuple[float, float]:
    """Return ``(zone_low, zone_high)`` with ``zone_low <= zone_high``."""
    rng = float(htf_high) - float(htf_low)
    if rng <= 0.0:
        return (float(htf_low), float(htf_high))
    if fib_lo > fib_hi:
        fib_lo, fib_hi = fib_hi, fib_lo
    if trend_up:
        z_lo = float(htf_high) - fib_hi * rng
        z_hi = float(htf_high) - fib_lo * rng
    else:
        z_lo = float(htf_low) + fib_lo * rng
        z_hi = float(htf_low) + fib_hi * rng
    if z_lo > z_hi:
        z_lo, z_hi = z_hi, z_lo
    return (z_lo, z_hi)


def spot_in_fib_zone(spot: float, side: str, zone: tuple[float, float]) -> bool:  # noqa: ARG001
    """Whether ``spot`` lies in the pullback band."""
    lo, hi = zone
    return lo <= float(spot) <= hi
