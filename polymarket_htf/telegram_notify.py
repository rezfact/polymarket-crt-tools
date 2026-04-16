"""
Send messages via **Telegram Bot API** (HTTPS ``sendMessage``).

Requires ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` in the environment (or ``.env``).
Optional: ``TELEGRAM_MESSAGE_THREAD_ID`` for forum/supergroup topics.

Used by ``scripts/healthcheck_telegram.py``, ``scripts/redeem_hourly.py``, and
``scripts/live_follow_paper_fill.py`` (when ``TELEGRAM_*`` is set).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def telegram_credentials_ok() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip())


def send_telegram_message(
    text: str,
    *,
    disable_notification: bool = False,
    timeout_sec: float = 25.0,
) -> bool:
    """
    POST ``sendMessage``. Returns ``True`` on HTTP 200 and Telegram ``ok``.

    If credentials are missing, returns ``False`` without raising (safe no-op for dev).
    """
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat,
        "text": str(text)[:4096],
        "disable_notification": bool(disable_notification),
    }
    tid = (os.getenv("TELEGRAM_MESSAGE_THREAD_ID") or "").strip()
    if tid.isdigit():
        payload["message_thread_id"] = int(tid)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return bool(data.get("ok"))


def format_healthcheck_message(*, label: str = "healthcheck") -> str:
    """Default body for periodic liveness pings."""
    import socket
    from datetime import datetime, timezone

    host = socket.gethostname()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{label}\nhost={host}\n{ts}"
