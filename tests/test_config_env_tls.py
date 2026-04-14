import os

import pytest

from polymarket_htf import config_env


def test_requests_verify_truthy_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REQUESTS_VERIFY", raising=False)
    assert config_env.requests_verify() is True
    monkeypatch.setenv("REQUESTS_VERIFY", "1")
    assert config_env.requests_verify() is True
    monkeypatch.setenv("REQUESTS_VERIFY", "true")
    assert config_env.requests_verify() is True
    monkeypatch.setenv("REQUESTS_VERIFY", "0")
    assert config_env.requests_verify() is False


def test_ensure_certifi_drops_bad_ssl_cert_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    bad = str(tmp_path / "nope.pem")
    monkeypatch.setenv("SSL_CERT_FILE", bad)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("REQUESTS_VERIFY", raising=False)
    config_env.ensure_certifi_ssl_env()
    bundle = os.getenv("SSL_CERT_FILE")
    assert bundle and os.path.isfile(bundle)
