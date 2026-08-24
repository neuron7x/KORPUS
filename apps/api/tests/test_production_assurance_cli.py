from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_production_assurance_cli_accepts_repo_relative_paths(tmp_path: Path) -> None:
    out = tmp_path / "production-assurance.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/assemble_production_assurance.py",
            "--profile",
            "config/assurance/production-v1.json",
            "--gate-dir",
            "var/nonexistent-production-gates",
            "--out",
            str(out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["profile"] == "config/assurance/production-v1.json"
    assert payload["production_authorized"] is False
