from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_load_last_paper_fills(tmp_path: Path) -> None:
    from scripts.examine_paper_fills_live import load_last_paper_fills

    j = tmp_path / "j.jsonl"
    j.write_text(
        "\n".join(
            [
                json.dumps({"kind": "wss_diag", "x": 1}),
                json.dumps({"kind": "paper_fill", "slug": "a", "side": "UP", "T": 1}),
                json.dumps({"kind": "paper_fill", "slug": "b", "side": "DOWN", "T": 2}),
            ]
        ),
        encoding="utf-8",
    )
    rows = load_last_paper_fills(j, last=1)
    assert len(rows) == 1
    assert rows[0]["slug"] == "b"


def test_enrich_row_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import examine_paper_fills_live as mod

    def fake_fetch(slug: str):
        if slug == "missing":
            return None
        return {
            "markets": [
                {
                    "outcomePrices": "[0.52, 0.48]",
                    "clobTokenIds": '["tok_up", "tok_dn"]',
                }
            ]
        }

    monkeypatch.setattr("polymarket_htf.gamma.fetch_event_by_slug", fake_fetch)
    monkeypatch.setattr(mod, "clob_liquidity_summary", lambda _tid: {"clob_ok": True, "mid": 0.51})

    r = mod.enrich_row({"slug": "btc-updown-15m-x", "side": "UP", "T": 3}, toy_yes_mid=0.5)
    assert r["gamma_side_entry_mid"] == 0.52
    assert r["delta_toy_minus_gamma"] == pytest.approx(-0.02)
    assert r["clob"]["mid"] == 0.51
    assert "clob_smoke_hint" in r and r["clob_smoke_hint"] and "tok_up" in r["clob_smoke_hint"]
