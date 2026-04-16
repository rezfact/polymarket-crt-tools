#!/usr/bin/env python3
"""
Validate repo `.env` for VPS **paper** bots (Gamma + HTTP) without printing secret values.

Run on the VPS:  python3 deploy/check_vps_env.py
Or:             .venv/bin/python deploy/check_vps_env.py --env-file /opt/polymarket-crt-tools/.env
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        k, _, v = line.partition("=")
        key = k.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        out[key] = _strip_quotes(v)
    return out


DEFAULT_UA = "Mozilla/5.0 (compatible; polymarket_htf/0.1; +local)"


def systemd_env_file(unit: str) -> Path | None:
    try:
        cp = subprocess.run(
            ["systemctl", "show", "-p", "EnvironmentFiles", unit],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if cp.returncode != 0 or not cp.stdout:
        return None
    # EnvironmentFiles=/path/to/.env (ignore-errors)
    m = re.search(r"EnvironmentFiles=(.*)", cp.stdout.strip())
    if not m:
        return None
    rest = m.group(1).strip()
    if not rest or rest in ("-", "n/a", "[unset]"):
        return None
    raw = rest.split()[0]
    if raw in ("-", "n/a", ""):
        return None
    # systemd optional file prefix: `-` before path
    if raw.startswith("-"):
        raw = raw[1:].lstrip()
    p = Path(raw)
    if p.name.endswith(".env") or ".env" in p.name:
        return p
    return p if raw else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Check VPS .env for paper bot requirements (no secrets printed).")
    ap.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to .env (default: repo root .env, or first EnvironmentFiles= from --systemd-unit)",
    )
    ap.add_argument(
        "--systemd-unit",
        default="polymarket-crt-sweet-spot.service",
        help="Unit to read EnvironmentFiles= from when --env-file is omitted",
    )
    ap.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repo root for default .env path (default: parent of deploy/)",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit with code 1 if any required-for-VPS warning is present",
    )
    args = ap.parse_args()

    here = Path(__file__).resolve()
    root = (args.repo_root or here.parent.parent).resolve()
    env_path = args.env_file
    if env_path is None:
        env_path = systemd_env_file(args.systemd_unit) or (root / ".env")

    print(f"=== .env check (file: {env_path}) ===")
    critical = 0
    issues = 0
    if not env_path.is_file():
        print("[crit] .env file not found — systemd may still start, but Gamma/Pyth tuning will use code defaults only.")
        print("       Create one:  cp .env.example .env   then edit (see .env.example “Paper bots checklist”).")
        critical = 1
        d: dict[str, str] = {}
    elif not os_access_read(env_path):
        print(f"[crit] .env exists but is not readable by this user: {env_path}")
        critical = 1
        d = {}
    else:
        d = parse_dotenv(env_path)

    if critical and not d:
        print("=== Summary: critical — create or chmod .env (see .env.example paper bots checklist) ===")
        return 1 if args.strict else 0

    ua = (d.get("HTTP_USER_AGENT") or "").strip()
    if not ua:
        print("[warn] HTTP_USER_AGENT unset — Gamma may 403 from datacenters; set a normal browser UA (see .env.example).")
        issues += 1
    elif "compatible; polymarket_htf" in ua or ua == DEFAULT_UA:
        print("[warn] HTTP_USER_AGENT still looks like the library default bot string — set a real browser User-Agent on VPS.")
        issues += 1
    else:
        print("[ok] HTTP_USER_AGENT is set (value hidden)")

    ref = (d.get("POLYMARKET_GAMMA_REFERER") or "").strip()
    if ref:
        print("[ok] POLYMARKET_GAMMA_REFERER is set (value hidden)")
    else:
        print("[info] POLYMARKET_GAMMA_REFERER unset — code defaults to https://polymarket.com/")

    slug = (d.get("POLYMARKET_GAMMA_EVENT_SLUG_URL") or "").strip()
    if slug:
        print("[ok] POLYMARKET_GAMMA_EVENT_SLUG_URL is set (value hidden)")
    else:
        print("[info] POLYMARKET_GAMMA_EVENT_SLUG_URL unset — code default gamma slug URL is used")

    if (d.get("POLYMARKET_GAMMA_AUTHORIZATION") or "").strip():
        print("[ok] POLYMARKET_GAMMA_AUTHORIZATION is set (value hidden)")
    else:
        print("[info] POLYMARKET_GAMMA_AUTHORIZATION unset — normal for public Gamma reads")

    if (d.get("PYTH_API_KEY") or "").strip() or (d.get("PYTH_BENCHMARKS_API_KEY") or "").strip():
        print("[ok] PYTH_* API key present (value hidden) — helps Benchmarks rate limits at scale")
    else:
        print("[info] PYTH_API_KEY unset — fine until Pyth/Benchmarks throttles; then set per .env.example")

    if (d.get("STRATEGY_EVAL_JOURNAL") or d.get("LIVE_EVAL_JOURNAL") or "").strip():
        print("[ok] STRATEGY_EVAL_JOURNAL or LIVE_EVAL_JOURNAL set (path hidden)")
    else:
        print("[info] STRATEGY_EVAL_JOURNAL unset — optional second combined JSONL")

    rv = (d.get("REQUESTS_VERIFY") or "").strip().lower()
    if rv in {"0", "false", "no", "off"}:
        print("[warn] REQUESTS_VERIFY disables TLS verification — dev only; do not use on production VPS.")
        issues += 1

    print()
    if critical and issues:
        print(f"=== Summary: {critical} critical, {issues} warning(s) ===")
    elif critical:
        print(f"=== Summary: {critical} critical issue(s) ===")
    elif issues:
        print(f"=== Summary: {issues} warning(s) — address before relying on Gamma at scale ===")
    else:
        print("=== Summary: paper-bot .env basics look fine (see messages above) ===")

    if args.strict and (critical or issues):
        return 1
    return 0


def os_access_read(p: Path) -> bool:
    import os

    return os.access(p, os.R_OK)


if __name__ == "__main__":
    raise SystemExit(main())
