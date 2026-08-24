from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_bounded_assurance_model_checker_has_no_counterexample() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/model_check_assurance.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "PASS"
    assert report["total_states_checked"] >= 12000
