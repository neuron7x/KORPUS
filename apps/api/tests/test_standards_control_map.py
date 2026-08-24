from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_standards_control_map_is_well_formed_and_all_local_evidence_exists() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/verify_standards_control_map.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "PASS"
    assert payload["references"] >= 9
    assert payload["controls"] >= 9
    assert payload["external_required_controls"] >= 2
