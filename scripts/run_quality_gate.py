#!/usr/bin/env python3
"""Execute ruff and mypy and leave an artifact proving they ran.

Until 2026-08-04 the assurance report carried the string
``"ruff": "NOT_EXECUTED_LOCAL_PACKAGE_UNAVAILABLE; REQUIRED_IN_GITLAB"`` next to
``"status": "PASS"``. The CI job did run both tools, but nothing downstream could
tell a green run from a run that never happened — the aggregate verdict was the
same either way. This writes the run itself down: command, exit code, violation
count, and the source tree the run applies to.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.provenance import PROVENANCE_KEY, stamp  # noqa: E402  (path set above)

RUFF = [
    sys.executable,
    "-m",
    "ruff",
    "check",
    "--output-format",
    "json",
    "apps/api/src",
    "apps/api/tests",
    "apps/api/migrations",
    "scripts",
]
MYPY = [
    sys.executable,
    "-m",
    "mypy",
    "--config-file",
    "apps/api/pyproject.toml",
]


def _run(
    command: list[str], env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(env_extra or {})
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _ruff_result() -> dict[str, object]:
    completed = _run(RUFF)
    try:
        violations = json.loads(completed.stdout or "[]")
        violation_count = len(violations) if isinstance(violations, list) else -1
    except json.JSONDecodeError:
        # ruff failing to start is not zero violations; a count that cannot be
        # read must not be reported as clean.
        violation_count = -1
    return {
        "command": " ".join(RUFF),
        "exit_code": completed.returncode,
        "violations": violation_count,
        "status": "PASS" if completed.returncode == 0 and violation_count == 0 else "FAIL",
        "output_tail": completed.stdout[-2000:],
    }


def _mypy_result() -> dict[str, object]:
    completed = _run(MYPY, {"MYPYPATH": str(ROOT / "apps/api/src")})
    return {
        "command": " ".join(MYPY),
        "exit_code": completed.returncode,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "output_tail": completed.stdout[-2000:],
    }


def main() -> int:
    tools = {"ruff": _ruff_result(), "mypy": _mypy_result()}
    report = {
        "schema_version": 1,
        "status": "PASS" if all(tool["status"] == "PASS" for tool in tools.values()) else "FAIL",
        "tools": tools,
        PROVENANCE_KEY: stamp(ROOT, "scripts/run_quality_gate.py"),
    }
    output = ROOT / "var/quality-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "ruff": {k: v for k, v in tools["ruff"].items() if k != "output_tail"},
                "mypy": {k: v for k, v in tools["mypy"].items() if k != "output_tail"},
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
