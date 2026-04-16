from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _crt_row(
    *,
    ts: str,
    side: str,
    o: float,
    h: float,
    l: float,
    c: float,
    rp: float,
    reason: str = "",
) -> dict:
    return {
        "kind": "crt_bar",
        "asset": "btc",
        "timestamp": ts,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": 0.0,
        "crh": h,
        "crl": l,
        "htf_rp_c1": rp,
        "ctx_high": h + 10,
        "ctx_low": l - 10,
        "side": side,
        "reason": reason or ("-" if side != "SKIP" else "crt_no_manipulation"),
    }


def test_analyze_crt_exports_smoke(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    py = root / ".venv313" / "bin" / "python"
    script = root / "scripts" / "analyze_crt_exports.py"
    crt = tmp_path / "t.jsonl"
    wss = tmp_path / "w.jsonl"
    rows = [
        _crt_row(ts="2026-01-01 00:00:00+00:00", side="SKIP", o=1, h=1, l=1, c=1, rp=0.5, reason="crt_no_manipulation"),
        _crt_row(ts="2026-01-01 00:15:00+00:00", side="UP", o=100, h=101, l=99, c=100.5, rp=0.2),
        _crt_row(ts="2026-01-01 00:30:00+00:00", side="SKIP", o=1, h=1, l=1, c=1, rp=0.5, reason="crt_no_distribution_inside"),
        _crt_row(ts="2026-01-01 00:45:00+00:00", side="DOWN", o=50, h=51, l=49, c=50.2, rp=0.8),
        _crt_row(ts="2026-01-01 01:00:00+00:00", side="SKIP", o=1, h=1, l=1, c=1, rp=0.5, reason="crt_no_manipulation"),
    ]
    crt.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    wss.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "kind": "wss_sim",
                        "asset": "btc",
                        "arm_bar_ts": "2026-01-01 00:15:00+00:00",
                        "side": "UP",
                        "slug": "x",
                        "T": 1,
                        "T_end": 2,
                        "trend_up": True,
                        "result": "timeout",
                    }
                ),
                json.dumps(
                    {
                        "kind": "wss_sim",
                        "asset": "btc",
                        "arm_bar_ts": "2026-01-01 00:45:00+00:00",
                        "side": "DOWN",
                        "slug": "y",
                        "T": 1,
                        "T_end": 2,
                        "trend_up": False,
                        "result": "paper_fill",
                        "settlement_tie": False,
                        "side_win": True,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cp = subprocess.run(
        [str(py), str(script), str(crt), "--wss", str(wss)],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert cp.returncode == 0, cp.stderr + cp.stdout
    out = cp.stdout
    assert "crt_no_distribution_inside" in out
    assert "crt_no_manipulation" in out
    assert "Toy by side" in out
    assert "paper_fill" in out
    assert "WSS result × side" in out
    assert "WSS paper_fill" in out


def test_analyze_crt_exports_range_filters(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    py = root / ".venv313" / "bin" / "python"
    script = root / "scripts" / "analyze_crt_exports.py"
    crt = tmp_path / "r.jsonl"
    rows = [
        _crt_row(ts="2026-02-01 00:00:00+00:00", side="SKIP", o=1, h=1, l=1, c=1, rp=0.5, reason="out_of_range"),
        _crt_row(ts="2026-02-10 00:00:00+00:00", side="UP", o=10, h=11, l=9, c=10, rp=0.4),
        _crt_row(ts="2026-02-10 00:15:00+00:00", side="SKIP", o=1, h=1, l=1, c=11, rp=0.5, reason="in_range_only"),
    ]
    crt.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    cp = subprocess.run(
        [
            str(py),
            str(script),
            str(crt),
            "--range-start",
            "2026-02-10",
            "--range-end",
            "2026-02-11",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert cp.returncode == 0, cp.stderr + cp.stdout
    assert "rows_in_range=2" in cp.stdout.replace(" ", "")
    assert "in_range_only" in cp.stdout
    assert "out_of_range" not in cp.stdout
