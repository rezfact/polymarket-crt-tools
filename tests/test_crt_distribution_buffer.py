from __future__ import annotations

import pandas as pd

from polymarket_htf.crt_strategy import CRTParams, attach_crt_features, crt_signal_row


def test_distribution_inside_buffer_flips_signal() -> None:
    """Marginal C3 close: strict inside fails; small buffer passes bearish AMD."""
    idx = pd.date_range("2024-06-01", periods=5, freq="15min", tz="UTC")
    exec_df = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 100.0, 99.0],
            "high": [101.0, 101.0, 102.0, 103.0, 101.0],
            "low": [99.0, 99.0, 98.0, 99.0, 98.5],
            "close": [100.0, 100.0, 102.0, 99.5, 102.01],
            "volume": [1000.0] * 5,
        },
        index=idx,
    )
    ctx_high = pd.Series([110.0] * 5, index=idx)
    ctx_low = pd.Series([90.0] * 5, index=idx)

    p_strict = CRTParams(
        use_htf_location_filter=True,
        htf_premium_min=0.58,
        distribution_inside_buffer_frac=0.0,
    )
    p_loose = CRTParams(
        use_htf_location_filter=True,
        htf_premium_min=0.58,
        distribution_inside_buffer_frac=0.01,
    )

    row_s = attach_crt_features(exec_df.copy(), ctx_high, ctx_low, params=p_strict).iloc[-1]
    row_l = attach_crt_features(exec_df.copy(), ctx_high, ctx_low, params=p_loose).iloc[-1]

    side_s, reason_s = crt_signal_row(row_s, params=p_strict)
    side_l, reason_l = crt_signal_row(row_l, params=p_loose)

    assert side_s == "SKIP"
    assert "distribution" in reason_s
    assert side_l == "DOWN"
    assert "bear" in reason_l
