from __future__ import annotations

from polymarket_htf.gamma import gamma_side_price_gate, gamma_yes_no_mids


def test_gamma_yes_no_mids_from_event() -> None:
    ev = {"markets": [{"outcomePrices": "[0.35, 0.65]"}]}
    assert gamma_yes_no_mids(ev) == (0.35, 0.65)


def test_side_price_gate_disabled() -> None:
    ev = {"markets": [{"outcomePrices": "[0.05, 0.95]"}]}
    ok, det = gamma_side_price_gate(ev, side="DOWN", min_side_price=None, max_side_price=None)
    assert ok is True
    assert det.get("min") is None


def test_side_price_gate_blocks_cheap_down() -> None:
    ev = {"markets": [{"outcomePrices": "[0.06, 0.94]"}]}
    ok, det = gamma_side_price_gate(ev, side="DOWN", min_side_price=0.12, max_side_price=0.88)
    assert ok is False
    assert det["price"] == 0.94


def test_side_price_gate_allows_mid_band() -> None:
    ev = {"markets": [{"outcomePrices": "[0.45, 0.55]"}]}
    ok, _ = gamma_side_price_gate(ev, side="UP", min_side_price=0.12, max_side_price=0.88)
    assert ok is True
