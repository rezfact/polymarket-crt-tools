"""Shared entry helpers for repo scripts (path + optional ``.env``)."""
from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_on_path_and_load_dotenv(project_root: Path) -> None:
    """Insert ``project_root`` on ``sys.path`` and load ``.env`` (see :func:`polymarket_htf.config_env.load_dotenv_files`)."""
    r = str(project_root.resolve())
    if r not in sys.path:
        sys.path.insert(0, r)
    from polymarket_htf.config_env import load_dotenv_files

    load_dotenv_files(project_root=project_root.resolve())
