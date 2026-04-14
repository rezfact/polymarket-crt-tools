from __future__ import annotations

import json
from pathlib import Path

import pytest

from polymarket_htf.journal import append_jsonl_with_eval_mirror


def test_append_jsonl_with_eval_mirror_skips_when_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("STRATEGY_EVAL_JOURNAL", raising=False)
    monkeypatch.delenv("LIVE_EVAL_JOURNAL", raising=False)
    primary = tmp_path / "p.jsonl"
    append_jsonl_with_eval_mirror(primary, {"a": 1}, pipeline="dryrun")
    assert primary.read_text(encoding="utf-8").strip() == '{"a": 1}'


def test_append_jsonl_with_eval_mirror_writes_eval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    primary = tmp_path / "p.jsonl"
    evalp = tmp_path / "eval.jsonl"
    monkeypatch.setenv("STRATEGY_EVAL_JOURNAL", str(evalp))
    append_jsonl_with_eval_mirror(primary, {"kind": "x"}, pipeline="sweet_spot")
    assert primary.read_text(encoding="utf-8").strip() == '{"kind": "x"}'
    row = json.loads(evalp.read_text(encoding="utf-8").strip())
    assert row == {"kind": "x", "pipeline": "sweet_spot"}


def test_append_jsonl_with_eval_mirror_skips_same_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    primary = tmp_path / "same.jsonl"
    monkeypatch.setenv("STRATEGY_EVAL_JOURNAL", str(primary))
    append_jsonl_with_eval_mirror(primary, {"b": 2}, pipeline="dryrun")
    lines = primary.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
