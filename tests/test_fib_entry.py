from __future__ import annotations

from polymarket_htf.fib_entry import fib_pullback_zone, fib_spot_metrics, spot_in_fib_zone


def test_fib_pullback_uptrend_zone_order() -> None:
    lo, hi = fib_pullback_zone(100.0, 90.0, True, fib_lo=0.618, fib_hi=0.786)
    assert lo < hi
    assert 90.0 < lo < hi < 100.0


def test_spot_in_zone() -> None:
    z = fib_pullback_zone(100.0, 90.0, True)
    assert spot_in_fib_zone((z[0] + z[1]) / 2, "UP", z)


def test_fib_spot_metrics_inside_and_outside() -> None:
    z = (94.0, 96.0)
    m_mid = fib_spot_metrics(95.0, z)
    assert m_mid["in_fib"] is True
    assert m_mid["dist_below_fib_lo"] == 0.0
    assert m_mid["dist_above_fib_hi"] == 0.0
    m_low = fib_spot_metrics(93.0, z)
    assert m_low["in_fib"] is False
    assert m_low["dist_below_fib_lo"] == 1.0
    assert m_low["dist_above_fib_hi"] == 0.0
