from __future__ import annotations

import pandas as pd
import pytest

from polymarket_htf.watch_session import SweetSpotWatchParams, SweetSpotWatchSession


def test_paper_settlement_row_binance_proxy_up_win(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = pd.Timestamp("2026-01-01 12:00:00+00:00")
    t1 = pd.Timestamp("2026-01-01 12:03:00+00:00")

    def fake_fetch(
        sym: str,
        interval: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        **kwargs: object,
    ) -> pd.DataFrame:
        assert sym.upper().startswith("BTC")
        assert interval == "1m"
        idx = pd.date_range(start, periods=3, freq="1min", tz="UTC")
        return pd.DataFrame({"close": [100.0, 101.0, 103.0]}, index=idx)

    monkeypatch.setattr("polymarket_htf.watch_session.fetch_binance_klines_range", fake_fetch)

    p = SweetSpotWatchParams(
        asset="btc",
        settlement_stake_usd=10.0,
        settlement_yes_mid=0.5,
        settlement_fee_roundtrip_bps=0.0,
    )
    sess = SweetSpotWatchSession(p)
    T = int(t0.timestamp())
    T_end = int(t1.timestamp())
    pen = {
        "slug": "btc-updown-15m-test",
        "side": "UP",
        "T": T,
        "T_end": T_end,
        "fill_spot": 101.0,
        "fill_chainlink_updated_at": 123,
    }
    row = sess._paper_settlement_row(pen)
    assert row["kind"] == "paper_settlement"
    assert row["result"] == "ok"
    assert row["settlement_proxy"] == "binance_1m_first_last_close"
    assert row["underlying_up"] is True
    assert row["side_win"] is True
    assert float(row["suggested_pnl_net_usd"]) > 9.0


def test_flush_pending_drops_after_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(*a, **k):
        idx = pd.date_range("2026-01-01 12:00", periods=2, freq="1min", tz="UTC")
        return pd.DataFrame({"close": [100.0, 99.0]}, index=idx)

    monkeypatch.setattr("polymarket_htf.watch_session.fetch_binance_klines_range", fake_fetch)

    p = SweetSpotWatchParams(asset="btc", settlement_buffer_sec=0.0, settlement_stake_usd=None)
    sess = SweetSpotWatchSession(p)
    T = int(pd.Timestamp("2026-01-01 12:00:00+00:00").timestamp())
    T_end = int(pd.Timestamp("2026-01-01 12:02:00+00:00").timestamp())
    sess._pending_settlements.append(
        {"slug": "x", "side": "DOWN", "T": T, "T_end": T_end, "fill_spot": 99.5, "fill_chainlink_updated_at": 1}
    )
    out: list = []
    sess._flush_pending_settlements(float(T_end) + 1.0, out)
    assert len(out) == 1
    assert out[0]["kind"] == "paper_settlement"
    assert out[0]["side_win"] is True  # DOWN wins when settle < open
    assert not sess._pending_settlements
