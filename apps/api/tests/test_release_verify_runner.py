from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/run_release_verify.py"
SPEC = importlib.util.spec_from_file_location("run_release_verify", SCRIPT)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_make_steps_bind_the_current_interpreter_without_splitting_spaces() -> None:
    assert RUNNER.make_command("api-test", "/tmp/korpus-venv/bin/python") == [
        "make",
        "api-test",
        "PY=/tmp/korpus-venv/bin/python",
    ]


def test_no_space_alias_preserves_the_active_virtual_environment() -> None:
    with RUNNER.interpreter_for_make() as executable:
        assert not any(char.isspace() for char in executable)
        completed = subprocess.run(
            [executable, "-c", "import pathlib,sys; print(pathlib.Path(sys.prefix).resolve())"],
            capture_output=True,
            text=True,
            check=True,
        )
    assert completed.stdout.strip() == str(Path(sys.prefix).resolve())
