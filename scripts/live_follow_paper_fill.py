#!/usr/bin/env python3
"""
At most **one** small CLOB **BUY** per new ``paper_fill`` row in ``watch_sweet_spot`` JSONL.

**Telegram:** set ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` (see ``.env.example``). When live
mode is on (``--execute``), important outcomes are sent to Telegram. Disable with
``LIVE_FOLLOW_TELEGRAM=0``. Add ``LIVE_FOLLOW_TELEGRAM_VERBOSE=1`` to also notify ``plan_only`` and
every ``skip_clob_book`` (can be noisy).

**Guards** (all must pass for ``--execute``):

- ``LIVE_TRADING_ENABLED=1``
- No kill-switch file (``LIVE_KILL_SWITCH_PATH``)
- Optional ``LIVE_TRADING_MIN_COLLATERAL_USD`` (e.g. ``1``): skip if CLOB collateral balance is **≤** this
  (when balance cannot be read, the order is **still attempted** so a misconfigured API does not brick you).
- Notional cap: ``LIVE_FOLLOW_PAPER_MAX_USD`` (default ``1``) or ``--max-usd``

**Dedupe**: each ``slug|T|side`` is processed once (byte offset + ``processed_keys.txt`` under ``--state-dir``).

Default without ``--execute``: logs a **plan** and still **marks the fill processed** (no CLOB submit). A dry
``--once`` run therefore **consumes** those fills for a later ``--execute`` pass — remove or archive
``--state-dir`` first if you want real orders on the same historical lines.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _extract_order_id(resp: object) -> str | None:
    if not isinstance(resp, dict):
        return None
    for k in ("orderID", "orderId", "order_id", "id"):
        v = resp.get(k)
        if v:
            return str(v)
    return None


def _safe_order_snapshot(client, order_id: str) -> tuple[dict | None, str | None]:
    # py_clob_client versions differ; try multiple lookups and never raise from telemetry paths.
    for meth_name in ("get_order", "get_order_by_id", "get_order_status"):
        meth = getattr(client, meth_name, None)
        if callable(meth):
            try:
                snap = meth(order_id)
                if isinstance(snap, dict):
                    return snap, None
                return {"raw": snap}, None
            except Exception as e:
                return None, f"{meth_name}: {type(e).__name__}: {e}"[:400]
    meth = getattr(client, "get_orders", None)
    if not callable(meth):
        return None, "no_order_lookup_method"
    try:
        rows = meth()
    except Exception as e:
        return None, f"get_orders: {type(e).__name__}: {e}"[:400]
    if not isinstance(rows, list):
        return None, "get_orders_not_list"
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = row.get("id") or row.get("orderID") or row.get("orderId") or row.get("order_id")
        if rid and str(rid) == order_id:
            return row, None
    return None, "order_not_found_in_open_orders"


def fill_key(row: dict) -> str:
    slug = str(row.get("slug", "")).strip()
    side = str(row.get("side", "")).strip().upper()
    t = int(row.get("T") or 0)
    return f"{slug}|{t}|{side}"


def read_incremental_lines(path: Path, offset: int, carry: bytes) -> tuple[list[str], int, bytes]:
    if not path.is_file():
        return [], offset, carry
    with path.open("rb") as f:
        f.seek(offset)
        chunk = f.read()
    if not chunk:
        return [], offset, carry
    data = carry + chunk
    last_nl = data.rfind(b"\n")
    if last_nl < 0:
        return [], offset, data
    complete = data[: last_nl + 1]
    rest = data[last_nl + 1 :]
    text = complete.decode("utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    new_offset = offset + len(complete)
    return lines, new_offset, rest


def load_processed(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    out: set[str] = set()
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            k = line.strip()
            if k:
                out.add(k)
    return out


def append_processed(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(key + "\n")
        f.flush()
        os.fsync(f.fileno())


def append_audit(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
        f.flush()


def handle_one_fill(
    row: dict,
    *,
    fill_key_str: str,
    execute: bool,
    max_usd: float,
    min_collateral: float | None,
    client,
) -> dict:
    from polymarket_htf.clob_collateral import clob_collateral_balance_usd
    from polymarket_htf.clob_plan import plan_buy_limit_notional
    from polymarket_htf.config_env import (
        live_kill_switch_path,
        live_trading_enabled,
        live_trading_paused_by_file,
    )
    from polymarket_htf.gamma import fetch_event_by_slug, gamma_clob_token_ids_up_down
    from polymarket_htf.journal import utc_now_iso
    from polymarket_htf.redeem import redeem_query_address

    slug = str(row.get("slug", "")).strip()
    side = str(row.get("side", "")).strip().upper()
    out: dict = {
        "kind": "live_follow_paper",
        "ts": utc_now_iso(),
        "fill_key": fill_key_str,
        "slug": slug,
        "side": side,
        "execute": bool(execute),
    }
    if not slug or side not in ("UP", "DOWN"):
        out["result"] = "skip_bad_row"
        return out

    if execute:
        if not live_trading_enabled():
            out["result"] = "skip_live_disabled"
            return out
        if live_trading_paused_by_file():
            out["result"] = "skip_kill_switch"
            out["kill_switch"] = str(live_kill_switch_path() or "")
            return out
        if min_collateral is not None:
            bal = clob_collateral_balance_usd(client)
            out["collateral_balance_usd"] = bal
            if bal is not None and bal <= float(min_collateral):
                out["result"] = "skip_low_collateral"
                out["min_collateral_usd"] = float(min_collateral)
                return out

    ev = fetch_event_by_slug(slug)
    if ev is None:
        out["result"] = "skip_gamma_404"
        return out
    pair = gamma_clob_token_ids_up_down(ev)
    if not pair:
        out["result"] = "skip_no_clob_tokens"
        return out
    up_id, down_id = pair
    token_id = up_id if side == "UP" else down_id
    clob_side = "up" if side == "UP" else "down"
    out["token_id"] = token_id
    out["clob_side"] = clob_side

    try:
        price, size, meta = plan_buy_limit_notional(client=client, token_id=token_id, max_usd=float(max_usd))
    except Exception as e:
        out["result"] = "skip_clob_book"
        out["clob_book_error"] = f"{type(e).__name__}: {e}"[:500]
        return out
    out.update({"price": price, "size": size, "approx_usd": round(price * size, 6), "plan_meta": meta})
    addr = redeem_query_address()
    out["signer"] = addr

    if not execute:
        out["result"] = "plan_only"
        return out

    from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions
    from py_clob_client.order_builder.constants import BUY

    order_args = OrderArgs(token_id=token_id, price=float(price), size=float(size), side=BUY)
    resp = client.create_and_post_order(order_args, PartialCreateOrderOptions())
    out["result"] = "order_posted"
    out["response"] = resp
    oid = _extract_order_id(resp)
    if oid:
        out["order_id"] = oid
        snap, snap_err = _safe_order_snapshot(client, oid)
        if snap is not None:
            out["order_status_snapshot"] = snap
        if snap_err:
            out["order_status_lookup_error"] = snap_err
    bal_after = clob_collateral_balance_usd(client)
    out["collateral_balance_post_usd"] = bal_after
    return out


def _live_follow_telegram_ok() -> bool:
    if os.getenv("LIVE_FOLLOW_TELEGRAM", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    from polymarket_htf.telegram_notify import telegram_credentials_ok

    return telegram_credentials_ok()


def _notify_live_follow_result(res: dict, *, execute: bool) -> None:
    from polymarket_htf.telegram_notify import send_telegram_message

    if not _live_follow_telegram_ok():
        return
    r = str(res.get("result", ""))
    verbose = os.getenv("LIVE_FOLLOW_TELEGRAM_VERBOSE", "").strip().lower() in ("1", "true", "yes")
    if execute:
        base = {
            "order_posted",
            "skip_low_collateral",
            "skip_kill_switch",
            "skip_live_disabled",
            "skip_gamma_404",
            "skip_no_clob_tokens",
            "skip_bad_row",
        }
        if verbose:
            base |= {"skip_clob_book", "plan_only"}
        else:
            base.add("skip_clob_book")
        if r not in base:
            return
    else:
        if not verbose or r != "plan_only":
            return

    lines = [
        f"live_follow {r}",
        f"slug={res.get('slug')}",
        f"side={res.get('side')}",
        f"fill_key={res.get('fill_key')}",
    ]
    if res.get("approx_usd") is not None:
        lines.append(f"approx_usd={res.get('approx_usd')}")
    if r == "skip_low_collateral":
        lines.append(f"collateral_usd={res.get('collateral_balance_usd')}")
    if r == "skip_clob_book" and res.get("clob_book_error"):
        lines.append(str(res["clob_book_error"])[:400])
    if r == "skip_gamma_404":
        lines.append("gamma slug not found (expired or typo)")
    if r == "order_posted" and res.get("response") is not None:
        lines.append(f"response={str(res.get('response'))[:500]}")
    send_telegram_message("\n".join(lines))


def main() -> int:
    p = argparse.ArgumentParser(description="One guarded CLOB BUY per watch_sweet_spot paper_fill.")
    p.add_argument("--journal", type=Path, default=ROOT / "var" / "watch_sweet_spot.jsonl")
    p.add_argument("--state-dir", type=Path, default=ROOT / "var" / "live_follow_paper")
    p.add_argument("--interval-sec", type=float, default=4.0)
    p.add_argument("--execute", action="store_true", help="place real orders (requires LIVE_TRADING_ENABLED=1)")
    p.add_argument("--max-usd", type=float, default=None, help="override LIVE_FOLLOW_PAPER_MAX_USD")
    p.add_argument(
        "--min-collateral-usd",
        type=float,
        default=None,
        help="override LIVE_TRADING_MIN_COLLATERAL_USD (skip BUY if collateral ≤ this; unset env + unset flag = no check)",
    )
    p.add_argument("--once", action="store_true", help="process available lines then exit")
    args = p.parse_args()

    from polymarket_htf.config_env import (
        ensure_certifi_ssl_env,
        live_follow_paper_max_usd,
        live_trading_min_collateral_usd,
        load_dotenv_files,
    )

    ensure_certifi_ssl_env()
    load_dotenv_files(project_root=ROOT)

    journal = args.journal.resolve()
    state_dir = args.state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    offset_path = state_dir / "journal_byte_offset.txt"
    processed_path = state_dir / "processed_keys.txt"
    audit_path = state_dir / "follow_audit.jsonl"

    max_usd = float(args.max_usd) if args.max_usd is not None else float(live_follow_paper_max_usd())
    min_collateral = (
        float(args.min_collateral_usd)
        if args.min_collateral_usd is not None
        else live_trading_min_collateral_usd()
    )

    from polymarket_htf.clob_account import make_trading_clob_client
    from polymarket_htf.telegram_notify import send_telegram_message

    client = make_trading_clob_client()

    if args.execute and _live_follow_telegram_ok():
        host = socket.gethostname()
        send_telegram_message(
            f"live_follow_paper_fill START --execute\nhost={host}\njournal={journal}\nmax_usd={max_usd}"
        )

    processed = load_processed(processed_path)
    carry = b""
    offset = 0
    if offset_path.is_file():
        try:
            offset = int(offset_path.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            offset = 0

    def persist_offset(off: int) -> None:
        offset_path.write_text(str(off), encoding="utf-8")

    while True:
        lines, new_off, carry = read_incremental_lines(journal, offset, carry)

        for line in lines:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(obj.get("kind", "")) != "paper_fill":
                continue
            fk = fill_key(obj)
            if fk in processed:
                continue
            res = handle_one_fill(
                obj,
                fill_key_str=fk,
                execute=bool(args.execute),
                max_usd=max_usd,
                min_collateral=min_collateral,
                client=client,
            )
            append_audit(audit_path, res)
            print(json.dumps(res, default=str))
            _notify_live_follow_result(res, execute=bool(args.execute))
            append_processed(processed_path, fk)
            processed.add(fk)

        if new_off != offset or lines:
            offset = new_off
            persist_offset(offset)

        if args.once:
            break
        time.sleep(float(args.interval_sec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
