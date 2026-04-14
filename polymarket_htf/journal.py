from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def append_jsonl_with_eval_mirror(
    primary: Path,
    record: dict[str, Any],
    *,
    pipeline: str,
) -> None:
    """
    Write ``record`` to ``primary``, and if :func:`polymarket_htf.config_env.strategy_eval_journal_path`
    is set, append the same row plus ``pipeline`` there (for one combined eval file across processes).
    """
    append_jsonl(primary, record)
    try:
        from polymarket_htf.config_env import strategy_eval_journal_path
    except ImportError:
        return
    eval_path = strategy_eval_journal_path()
    if eval_path is None:
        return
    try:
        if eval_path.resolve() == Path(primary).expanduser().resolve():
            return
    except OSError:
        return
    row = dict(record)
    row["pipeline"] = pipeline
    append_jsonl(eval_path, row)
