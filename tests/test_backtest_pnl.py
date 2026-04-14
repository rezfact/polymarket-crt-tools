from __future__ import annotations

import pandas as pd

from polymarket_htf.backtest_crt import _pnl_binary, share_settlement, summarize_toy_crt_trades


def test_pnl_up_win_50c() -> None:
    # stake 10, p=0.5, shares=20, payoff 20, pnl = 10
    assert abs(_pnl_binary(stake=10.0, win=True, side="UP", yes_mid=0.5) - 10.0) < 1e-9


def test_pnl_lose() -> None:
    assert _pnl_binary(stake=10.0, win=False, side="UP", yes_mid=0.5) == -10.0


def test_share_settlement_explicit() -> None:
    s = share_settlement(usdc_spent=10.0, win=True, side="UP", yes_mid=0.5)
    assert abs(s.shares - 20.0) < 1e-9
    assert abs(s.redemption_usd - 20.0) < 1e-9
    assert abs(s.pnl_gross - 10.0) < 1e-9


def test_down_uses_no_mid_when_set() -> None:
    s = share_settlement(usdc_spent=10.0, win=True, side="DOWN", yes_mid=0.5, no_mid=0.48)
    assert abs(s.shares - 10.0 / 0.48) < 1e-6


def test_roundtrip_fee_is_bps_of_stake() -> None:
    stake = 100.0
    fee_rt = 100.0 / 10_000.0  # 100 bps = 1%
    assert stake * fee_rt == 1.0


def test_summarize_toy_crt_trades_one_up_win() -> None:
    ix = pd.date_range("2026-01-01", periods=3, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "close": [100.5, 102.0, 103.0],
            "side": ["UP", "SKIP", "SKIP"],
        },
        index=ix,
    )
    m = (df.index >= ix[0]) & (df.index < ix[1])
    out = summarize_toy_crt_trades(df, range_mask=m, stake_usd=10.0)
    assert out["trades"] == 1
    assert out["wins"] == 1
    assert out["losses"] == 0
    assert abs(float(out["pnl_net_usd"]) - 10.0) < 1e-9


def test_summarize_toy_crt_trades_down_loss_when_next_up() -> None:
    ix = pd.date_range("2026-01-01", periods=2, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {"open": [100.0, 101.0], "close": [100.5, 102.0], "side": ["DOWN", "SKIP"]},
        index=ix,
    )
    m = df.index == ix[0]
    out = summarize_toy_crt_trades(df, range_mask=m, stake_usd=10.0)
    assert out["trades"] == 1
    assert out["wins"] == 0
    assert abs(float(out["pnl_net_usd"]) + 10.0) < 1e-9


def test_capital_updates_with_fee_on_win() -> None:
    capital = 100.0
    stake = 10.0
    fee_rt = 50.0 / 10_000.0
    pnl_gross = _pnl_binary(stake=stake, win=True, side="UP", yes_mid=0.5)
    fee = stake * fee_rt
    capital += pnl_gross - fee
    assert pnl_gross == 10.0
    assert fee == 0.05
    assert capital == 109.95
