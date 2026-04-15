from __future__ import annotations

from polymarket_htf.sizing import trade_usd_from_capital


def test_examples_from_user() -> None:
    assert trade_usd_from_capital(5) == 1.0
    assert trade_usd_from_capital(10) == 1.0
    assert trade_usd_from_capital(15) == 1.0
    assert trade_usd_from_capital(20) == 2.0


def test_cap_below_min_no_trade() -> None:
    assert trade_usd_from_capital(0.5) == 0.0


def test_cap_capped() -> None:
    # weird edge: if capital 1, floor(0.1)=0, max(1,0)=1, min(1,1)=1
    assert trade_usd_from_capital(1.0) == 1.0


def test_larger() -> None:
    assert trade_usd_from_capital(100) == 10.0
    assert trade_usd_from_capital(105) == 10.0  # floor(10.5)=10


def test_cap_at_200_still_10() -> None:
    assert trade_usd_from_capital(200) == 10.0


def test_custom_max_stake_1() -> None:
    assert trade_usd_from_capital(200, max_stake_usd=1.0) == 1.0


def test_uncapped_when_max_disabled() -> None:
    assert trade_usd_from_capital(200, max_stake_usd=None) == 20.0
