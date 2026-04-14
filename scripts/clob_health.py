#!/usr/bin/env python3
"""
Lightweight **CLOB + account health** for cron: ``get_ok``, server time, open order count.

Exits ``1`` if CLOB ``get_ok`` fails (use for systemd ``ExecStart`` + restart policy on parent stack).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="CLOB get_ok + open order count.")
    p.add_argument("--strict", action="store_true", help="exit 1 if get_ok fails")
    args = p.parse_args()

    from polymarket_htf.clob_account import make_trading_clob_client
    from polymarket_htf.config_env import load_dotenv_files

    load_dotenv_files(project_root=ROOT)

    client = make_trading_clob_client()
    ok = True
    try:
        client.get_ok()
    except Exception as e:
        ok = False
        err = str(e)[:200]
    else:
        err = None

    try:
        t = client.get_server_time()
    except Exception:
        t = None

    try:
        oo = client.get_orders()
        n = len(oo) if isinstance(oo, list) else 0
    except Exception:
        n = -1

    line = {"clob_ok": ok, "server_time": t, "open_orders": n, "error": err}
    print(json.dumps(line, default=str))
    if args.strict and not ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
