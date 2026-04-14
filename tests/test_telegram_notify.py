from __future__ import annotations

import json
from unittest.mock import patch

from polymarket_htf.telegram_notify import (
    format_healthcheck_message,
    send_telegram_message,
    telegram_credentials_ok,
)


def test_telegram_credentials_ok_false_when_empty(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert telegram_credentials_ok() is False


def test_telegram_credentials_ok_true(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    assert telegram_credentials_ok() is True


def test_send_returns_false_without_creds(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert send_telegram_message("hi") is False


def test_send_success_mocked(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"ok": True, "result": {"message_id": 1}}).encode()

    def fake_urlopen(*_a, **_k):
        return _Resp()

    with patch("polymarket_htf.telegram_notify.urllib.request.urlopen", fake_urlopen):
        assert send_telegram_message("hello") is True


def test_format_healthcheck_contains_host() -> None:
    s = format_healthcheck_message()
    assert "healthcheck" in s.lower()
    assert "UTC" in s
