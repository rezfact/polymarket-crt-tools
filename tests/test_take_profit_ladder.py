from pathlib import Path

import pytest

from polymarket_htf.take_profit_ladder import (
    linear_bridge_marks,
    load_ladder_state,
    merge_fired_for_tiers,
    parse_tiers_spec,
    plan_ladder_exits,
    position_mark,
    premium_return_pct,
    save_ladder_state,
    simulate_tp_ladder_on_bridge,
)


def test_premium_return_pct():
    assert premium_return_pct(0.1, 0.6) == pytest.approx(500.0)
    assert premium_return_pct(0.05, 0.55) == pytest.approx(1000.0)


def test_parse_tiers_spec_order():
    assert parse_tiers_spec("1000:1,500:0.5") == [(500.0, 0.5), (1000.0, 1.0)]


def test_parse_tiers_spec_bad():
    with pytest.raises(ValueError):
        parse_tiers_spec("")
    with pytest.raises(ValueError):
        parse_tiers_spec("500:1.1")


def test_plan_single_tier():
    tiers = [(500.0, 0.5)]
    fired = [False]
    planned, nf = plan_ladder_exits(avg_entry=0.1, mark=0.6, position_size=100.0, tiers=tiers, fired=fired)
    assert len(planned) == 1
    assert planned[0].shares == pytest.approx(50.0)
    assert nf == [True]


def test_plan_two_tiers_same_tick():
    tiers = [(500.0, 0.5), (1000.0, 1.0)]
    fired = [False, False]
    planned, nf = plan_ladder_exits(avg_entry=0.05, mark=0.55, position_size=100.0, tiers=tiers, fired=fired)
    assert len(planned) == 2
    assert planned[0].shares == pytest.approx(50.0)
    assert planned[1].shares == pytest.approx(50.0)
    assert nf == [True, True]


def test_plan_second_tier_only_after_first_fired():
    tiers = [(500.0, 0.5), (1000.0, 1.0)]
    fired = [True, False]
    planned, nf = plan_ladder_exits(avg_entry=0.1, mark=0.6, position_size=50.0, tiers=tiers, fired=fired)
    assert planned == []
    assert nf == [True, False]

    planned, nf = plan_ladder_exits(avg_entry=0.05, mark=0.55, position_size=50.0, tiers=tiers, fired=fired)
    assert len(planned) == 1
    assert planned[0].tier_index == 1
    assert planned[0].shares == pytest.approx(50.0)


def test_position_mark_bounds():
    assert position_mark({"curPrice": 0.5}) == 0.5
    assert position_mark({"curPrice": 1.0}) is None
    assert position_mark({"curPrice": 0.0}) is None


def test_linear_bridge_endpoints():
    m = linear_bridge_marks(0.1, 1.0, steps=3)
    assert m[0] == pytest.approx(0.1)
    assert m[-1] == pytest.approx(1.0)
    assert len(m) == 3


def test_simulate_tp_matches_hold_when_tiers_unreachable():
    usdc = 10.0
    entry = 0.5
    shares = usdc / entry
    tp = simulate_tp_ladder_on_bridge(
        usdc_spent=usdc,
        entry_price=entry,
        shares=shares,
        terminal_price=1.0,
        tiers=[(1_000_000.0, 0.5)],
        bridge_steps=32,
    )
    assert tp.pnl_gross == pytest.approx(shares - usdc)
    assert tp.events == []


def test_simulate_tp_partial_along_bridge():
    usdc = 1.0
    entry = 0.05
    shares = usdc / entry
    tp = simulate_tp_ladder_on_bridge(
        usdc_spent=usdc,
        entry_price=entry,
        shares=shares,
        terminal_price=1.0,
        tiers=[(500.0, 0.5), (1000.0, 1.0)],
        bridge_steps=128,
    )
    assert len(tp.events) >= 1
    assert tp.cash_from_sales + tp.final_redemption_usd == pytest.approx(tp.pnl_gross + usdc)


def test_state_roundtrip(tmp_path: Path):
    p = tmp_path / "s.json"
    st: dict[str, list[bool]] = {"k": [True, False]}
    save_ladder_state(p, st)
    assert load_ladder_state(p) == st
    merge_fired_for_tiers(st, "k", 2, [True, True])
    assert st["k"] == [True, True]
