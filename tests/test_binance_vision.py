from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from polymarket_htf.binance_vision import _month_starts_touching_range, read_spot_klines_zip


def test_month_starts_cross_quarter() -> None:
    s = pd.Timestamp("2025-11-17", tz="UTC")
    e = pd.Timestamp("2026-04-01", tz="UTC")
    m = _month_starts_touching_range(s, e)
    assert len(m) == 5
    assert (m[0].year, m[0].month) == (2025, 11)
    assert (m[-1].year, m[-1].month) == (2026, 3)


def test_read_klines_roundtrip(tmp_path: Path) -> None:
    # one Binance-style row: open_time, o, h, l, c, v, ...
    line = b"1700000000000,1.0,1.1,0.9,1.05,1234.5\n"
    zpath = tmp_path / "BTCUSDT-15m-2023-11.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("BTCUSDT-15m-2023-11.csv", line)
    df = read_spot_klines_zip(zpath)
    assert len(df) == 1
    assert df["close"].iloc[0] == 1.05
