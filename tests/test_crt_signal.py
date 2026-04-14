from __future__ import annotations

import pandas as pd

from polymarket_htf.crt_strategy import CRTParams, crt_signal_row


def _base_row(**over) -> pd.Series:
    r = {
        "crh": 100.0,
        "crl": 95.0,
        "c1_close": 97.0,
        "sweep_below_crl": False,
        "sweep_above_crh": False,
        "c3_inside_c1": False,
        "sweep_conflict": False,
        "c1_range_pct": 0.05,
        "htf_rp_c1": 0.35,
        "ctx_high": 110.0,
        "ctx_low": 90.0,
        "vol_ma": 100.0,
        "vol_confirm": True,
    }
    r.update(over)
    return pd.Series(r)


def test_crt_bullish_amd() -> None:
    p = CRTParams(use_htf_location_filter=True, require_volume_confirm=False)
    row = _base_row(
        sweep_below_crl=True,
        sweep_above_crh=False,
        c3_inside_c1=True,
        htf_rp_c1=0.35,
    )
    side, reason = crt_signal_row(row, params=p)
    assert side == "UP"
    assert "bull" in reason


def test_crt_bearish_amd() -> None:
    p = CRTParams(use_htf_location_filter=True)
    row = _base_row(
        sweep_below_crl=False,
        sweep_above_crh=True,
        c3_inside_c1=True,
        htf_rp_c1=0.72,
    )
    side, reason = crt_signal_row(row, params=p)
    assert side == "DOWN"
    assert "bear" in reason


def test_crt_htf_filter_blocks_bull() -> None:
    p = CRTParams(use_htf_location_filter=True, htf_discount_max=0.42)
    row = _base_row(
        sweep_below_crl=True,
        c3_inside_c1=True,
        htf_rp_c1=0.55,
    )
    side, _ = crt_signal_row(row, params=p)
    assert side == "SKIP"


def test_crt_sweep_conflict() -> None:
    p = CRTParams(use_htf_location_filter=False)
    row = _base_row(
        sweep_below_crl=True,
        sweep_above_crh=True,
        sweep_conflict=True,
        c3_inside_c1=True,
    )
    side, reason = crt_signal_row(row, params=p)
    assert side == "SKIP"
    assert "conflict" in reason


def test_crt_sweep_conflict_prefer_bull() -> None:
    p = CRTParams(use_htf_location_filter=False, sweep_conflict_resolve="prefer_bull")
    row = _base_row(
        sweep_below_crl=True,
        sweep_above_crh=True,
        sweep_conflict=True,
        c3_inside_c1=True,
        htf_rp_c1=0.35,
    )
    side, reason = crt_signal_row(row, params=p)
    assert side == "UP"
    assert "bull" in reason


def test_crt_range_too_tight() -> None:
    p = CRTParams(min_candle1_range_pct=0.1)
    row = _base_row(
        c1_range_pct=0.001,
        sweep_below_crl=True,
        c3_inside_c1=True,
    )
    side, reason = crt_signal_row(row, params=p)
    assert side == "SKIP"
    assert "tight" in reason
