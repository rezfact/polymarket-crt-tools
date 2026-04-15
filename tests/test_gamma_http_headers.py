from __future__ import annotations

from polymarket_htf.config_env import gamma_http_headers


def test_gamma_http_headers_defaults(monkeypatch) -> None:
    monkeypatch.delenv("POLYMARKET_GAMMA_REFERER", raising=False)
    monkeypatch.delenv("POLYMARKET_GAMMA_AUTHORIZATION", raising=False)
    monkeypatch.delenv("HTTP_USER_AGENT", raising=False)
    h = gamma_http_headers()
    assert h["Accept"] == "application/json"
    assert "polymarket.com" in h["Referer"].lower()
    assert "User-Agent" in h
    assert "Authorization" not in h


def test_gamma_http_headers_optional_auth(monkeypatch) -> None:
    monkeypatch.setenv("POLYMARKET_GAMMA_AUTHORIZATION", "Bearer test-token")
    h = gamma_http_headers()
    assert h["Authorization"] == "Bearer test-token"
