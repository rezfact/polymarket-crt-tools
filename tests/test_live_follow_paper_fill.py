from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_fill_key() -> None:
    from scripts.live_follow_paper_fill import fill_key

    assert fill_key({"slug": "x", "T": 3, "side": "up"}) == "x|3|UP"


def test_read_incremental_lines(tmp_path: Path) -> None:
    from scripts.live_follow_paper_fill import read_incremental_lines

    j = tmp_path / "j.jsonl"
    j.write_bytes(b'{"a":1}\n{"b":2}\n')
    lines, off, carry = read_incremental_lines(j, 0, b"")
    assert len(lines) == 2
    assert off == len(j.read_bytes())
    assert carry == b""

    j.write_bytes(j.read_bytes() + b'{"c":3}\n')
    lines2, off2, c2 = read_incremental_lines(j, off, carry)
    assert len(lines2) == 1
    assert json.loads(lines2[0])["c"] == 3
    assert c2 == b""


def test_handle_one_fill_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import live_follow_paper_fill as mod

    class FakeClient:
        pass

    def fake_fetch(slug: str):
        return {
            "markets": [
                {
                    "outcomePrices": "[0.51, 0.49]",
                    "clobTokenIds": '["tu", "td"]',
                }
            ]
        }

    monkeypatch.setattr("polymarket_htf.gamma.fetch_event_by_slug", fake_fetch)
    monkeypatch.setattr(
        "polymarket_htf.clob_plan.plan_buy_limit_notional",
        lambda **kw: (0.5, 2.0, {"mid": 0.5}),
    )
    monkeypatch.setattr("polymarket_htf.redeem.redeem_query_address", lambda: "0xabc")

    row = {"slug": "btc-updown-15m-1", "side": "DOWN", "T": 9}
    r = mod.handle_one_fill(
        row,
        fill_key_str=mod.fill_key(row),
        execute=False,
        max_usd=1.0,
        min_collateral=None,
        client=FakeClient(),
    )
    assert r["result"] == "plan_only"
    assert r["token_id"] == "td"


def test_notify_live_follow_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import live_follow_paper_fill as mod

    sent: list[str] = []

    monkeypatch.setenv("LIVE_FOLLOW_TELEGRAM", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr("polymarket_htf.telegram_notify.send_telegram_message", lambda text, **kw: sent.append(text) or True)

    mod._notify_live_follow_result(
        {"result": "order_posted", "slug": "s", "side": "UP", "fill_key": "k", "approx_usd": 1.0, "response": {"id": "x"}},
        execute=True,
    )
    assert sent and "order_posted" in sent[0]


def test_handle_low_collateral(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import live_follow_paper_fill as mod

    class FakeClient:
        pass

    monkeypatch.setattr("polymarket_htf.config_env.live_trading_enabled", lambda: True)
    monkeypatch.setattr("polymarket_htf.config_env.live_trading_paused_by_file", lambda: False)
    monkeypatch.setattr("polymarket_htf.clob_collateral.clob_collateral_balance_usd", lambda _c: 0.5)

    row = {"slug": "x", "side": "UP", "T": 1}
    r = mod.handle_one_fill(
        row,
        fill_key_str="x|1|UP",
        execute=True,
        max_usd=1.0,
        min_collateral=1.0,
        client=FakeClient(),
    )
    assert r["result"] == "skip_low_collateral"
