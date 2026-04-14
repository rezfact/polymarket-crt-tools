#!/usr/bin/env python3
"""
Send a one-line **Telegram healthcheck** (for cron / systemd timer, e.g. every hour).

Requires ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID``. Exits ``0`` on success, ``1`` on failure
or missing credentials (so monitors can alert).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_htf.config_env import load_dotenv_files
from polymarket_htf.telegram_notify import (
    format_healthcheck_message,
    send_telegram_message,
    telegram_credentials_ok,
)


def main() -> int:
    load_dotenv_files(project_root=ROOT)
    if not telegram_credentials_ok():
        print("error: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID", file=sys.stderr)
        return 1
    msg = format_healthcheck_message()
    ok = send_telegram_message(msg)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
