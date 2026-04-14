from __future__ import annotations

from polymarket_htf.fib_entry import fib_pullback_zone, spot_in_fib_zone


def test_fib_pullback_uptrend_zone_order() -> None:
    lo, hi = fib_pullback_zone(100.0, 90.0, True, fib_lo=0.618, fib_hi=0.786)
    assert lo < hi
    assert 90.0 < lo < hi < 100.0


def test_spot_in_zone() -> None:
    z = fib_pullback_zone(100.0, 90.0, True)
    assert spot_in_fib_zone((z[0] + z[1]) / 2, "UP", z)
