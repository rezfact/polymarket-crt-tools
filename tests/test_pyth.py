from __future__ import annotations

from polymarket_htf.config_env import pyth_benchmarks_request_headers
from polymarket_htf.hermes_latest import decode_scaled_price, default_feed_id_for_asset


def test_decode_scaled_price_negative_expo() -> None:
    assert abs(decode_scaled_price("221907972083", -8) - 2219.07972083) < 1e-6


def test_pyth_benchmarks_headers_no_key(monkeypatch) -> None:
    monkeypatch.delenv("PYTH_API_KEY", raising=False)
    monkeypatch.delenv("PYTH_BENCHMARKS_API_KEY", raising=False)
    monkeypatch.delenv("PYTH_API_KEY_HEADER", raising=False)
    h = pyth_benchmarks_request_headers()
    assert "User-Agent" in h
    assert "Authorization" not in h


def test_pyth_benchmarks_headers_bearer(monkeypatch) -> None:
    monkeypatch.setenv("PYTH_API_KEY", "secret-token")
    monkeypatch.delenv("PYTH_API_KEY_HEADER", raising=False)
    monkeypatch.delenv("PYTH_API_AUTH_SCHEME", raising=False)
    h = pyth_benchmarks_request_headers()
    assert h.get("Authorization") == "Bearer secret-token"


def test_pyth_benchmarks_headers_custom_header(monkeypatch) -> None:
    monkeypatch.setenv("PYTH_API_KEY", "abc")
    monkeypatch.setenv("PYTH_API_KEY_HEADER", "X-Custom-Key")
    h = pyth_benchmarks_request_headers()
    assert h.get("X-Custom-Key") == "abc"
    assert "Authorization" not in h


def test_default_feed_ids_are_hex() -> None:
    for a in ("btc", "eth", "sol"):
        fid = default_feed_id_for_asset(a)
        assert fid is not None
        assert len(fid) == 64
        int(fid, 16)
