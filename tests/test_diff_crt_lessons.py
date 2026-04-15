from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _minimal_lessons(*, up: int, down: int, skip: int, dist: int) -> dict:
    n = up + down + skip
    manip = skip - dist
    if manip < 0:
        manip = 0
    return {
        "meta": {"asset": "btc", "crt_preset": "loose"},
        "summary": {
            "bars": n,
            "counts_by_side": {"UP": up, "DOWN": down, "SKIP": skip},
            "counts_by_reason": {
                "crt_no_distribution_inside": dist,
                "crt_no_manipulation": manip,
                "crt_amd_bull_sweep_crl_c3_inside": up,
                "crt_amd_bear_sweep_crh_c3_inside": down,
            },
        },
        "tuning_dig": {
            "primary_skip_driver": "crt_no_distribution_inside",
            "up_down_ratio": round(up / down, 4) if down else None,
            "skip_mix_pct_of_all_bars": {"crt_no_distribution_inside": round(100.0 * dist / n, 2)},
            "suggested_ab_runs": [{"focus": "crt_no_distribution_inside", "next_experiment": "try loose_plus"}],
        },
    }


def test_diff_crt_lessons_script_smoke(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "diff_crt_lessons.py"
    pa = tmp_path / "a.json"
    pb = tmp_path / "b.json"
    pa.write_text(json.dumps(_minimal_lessons(up=10, down=10, skip=80, dist=70)), encoding="utf-8")
    pb.write_text(json.dumps(_minimal_lessons(up=15, down=10, skip=75, dist=65)), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(script), str(pa), str(pb)],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "UP:" in r.stdout
    assert "crt_no_distribution_inside" in r.stdout
