from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_current_release_identity_surfaces_agree() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/check_release_identity.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["valid"] is True


def test_release_identity_covers_handoff_and_package_surfaces() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/check_release_identity.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(completed.stdout)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    for key in (
        "package_index",
        "distribution_contract",
        "package_description",
        "gitlab_import",
        "handoff_release",
    ):
        assert payload["checks"][key] is True, f"release surface drift: {key}"
