from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from polymarket_htf.gamma import updown_window_candidate_ids, updown_window_open_epoch


def test_window_open_epoch_matches_candidate_center() -> None:
    now_ts = 1_775_000_000.0
    ids = updown_window_candidate_ids(tf_minutes=15, now_ts=now_ts, neighbor_windows=0)
    center = ids[0]
    dt = datetime.fromtimestamp(center, tz=timezone.utc)
    assert updown_window_open_epoch(ts_utc=dt, tf_minutes=15) == center


def test_window_open_epoch_accepts_pd_timestamp() -> None:
    now_ts = 1_775_000_000.0
    center = updown_window_candidate_ids(tf_minutes=15, now_ts=now_ts, neighbor_windows=0)[0]
    assert updown_window_open_epoch(ts_utc=pd.Timestamp(center, unit="s", tz="UTC"), tf_minutes=15) == center


def test_next_monitor_window_open_epoch_advances() -> None:
    from polymarket_htf.gamma import next_monitor_window_open_epoch

    bar_open = pd.Timestamp("2026-03-01 00:00:00+00:00")
    w0 = next_monitor_window_open_epoch(bar_open_utc=bar_open, tf_minutes=15, slug_offset_steps=0)
    w1 = next_monitor_window_open_epoch(bar_open_utc=bar_open, tf_minutes=15, slug_offset_steps=1)
    assert w1 - w0 == 900
