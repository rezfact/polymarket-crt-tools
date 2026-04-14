"""Re-exec CLI scripts with a **project** venv (stdlib only — safe before numpy imports)."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def using_project_venv(root: Path) -> bool:
    """True when ``sys.prefix`` is ``root/.venv313`` or ``root/.venv`` (deps belong here)."""
    return _running_in_repo_venv(root)


def _running_in_repo_venv(root: Path) -> bool:
    try:
        pref = Path(sys.prefix).resolve()
    except OSError:
        return False
    for name in (".venv313", ".venv"):
        try:
            if pref == (root / name).resolve():
                return True
        except OSError:
            continue
    return False


def _is_venv_python(py: Path) -> bool:
    """True if ``py`` is ``.../somevenv/bin/python`` (``pyvenv.cfg`` next to ``bin``).

    Must not use ``Path.resolve()`` here: ``bin/python`` often symlinks to the base
    interpreter; resolving would leave the venv tree and drop ``pyvenv.cfg``.
    """
    try:
        py = Path(py).expanduser().absolute()
    except OSError:
        return False
    if py.parent.name != "bin":
        return False
    return (py.parent.parent / "pyvenv.cfg").is_file()


def reexec_if_needed(*, root: Path, script: Path) -> None:
    """
    If ``sys.prefix`` is not ``root/.venv313`` or ``root/.venv``, ``execv`` the first
    valid venv interpreter among ``POLYMARKET_HTF_PYTHON`` (optional), ``.venv313``, ``.venv``.

    Skips ``POLYMARKET_HTF_PYTHON`` when it is not a venv (e.g. Homebrew ``python3.13``).
    """
    if os.environ.get("POLYMARKET_HTF_NO_VENV_REEXEC"):
        return
    if _running_in_repo_venv(root):
        return
    script = script.resolve()
    env_py = os.environ.get("POLYMARKET_HTF_PYTHON", "").strip()
    candidates: list[Path] = []
    if env_py:
        candidates.append(Path(env_py))
    candidates.extend(
        [
            root / ".venv313" / "bin" / "python",
            root / ".venv" / "bin" / "python",
        ]
    )
    for vpy in candidates:
        if not vpy.is_file() or not _is_venv_python(vpy):
            continue
        target = vpy.expanduser().absolute()
        os.environ.setdefault("PYTHONNOUSERSITE", "1")
        os.execv(str(target), [str(target), str(script), *sys.argv[1:]])
    print(
        "warn: no usable project venv (.venv313 / .venv with pyvenv.cfg). Create one:\n"
        f"  cd {root} && python3.13 -m venv .venv313 && .venv313/bin/python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
