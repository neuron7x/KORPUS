import os
import subprocess
import sys

from scripts.openapi_contract import DEFAULT, ROOT, canonical_contract


def test_openapi_contract_has_no_unreviewed_drift():
    assert DEFAULT.read_text(encoding="utf-8") == canonical_contract()


def test_openapi_contract_cli_runs_with_make_pythonpath():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "apps/api/src")
    completed = subprocess.run(
        [sys.executable, "scripts/openapi_contract.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "OpenAPI contract matches" in completed.stdout
