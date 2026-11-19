#!/usr/bin/env python3
"""Execute the fixed source scanners and preserve native results from this run.

The receipt is evidence within the authenticated Actions job, not deployment
authorization. Scanners never receive production credentials or runtime data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "apps/api/src")]

from scripts.coverage_execution_contract import SOURCE_INPUTS, snapshot, write_json  # noqa: E402
from scripts.source_security_commands import scanner_commands  # noqa: E402
from scripts.source_security_contract import (  # noqa: E402
    EXECUTION_NAMES,
    OUTPUT_MEMBERS,
    PIP_AUDIT_VERSION,
    SCHEMA,
    expected_tools,
    require,
    validate_outputs,
)
from scripts.source_security_lock import build_lock_sbom  # noqa: E402
from scripts.source_security_source import (  # noqa: E402
    admit_source,
    freeze_source,
    runner_temporary,
    verify_frozen_source,
    verify_source_after,
)
from scripts.trusted_system_tools import trusted_executable  # noqa: E402


def _environment() -> dict[str, str]:
    # No caller PYTHONPATH, pip configuration, scanner flags, Docker endpoint or
    # Git overrides enter the subprocess. Docker credentials use an empty dir.
    return {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"}


def execute(tool: str, command: list[str], output: Path, cwd: Path) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    with (output / f"{tool.replace(':', '-')}.log").open("wb") as log:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=_environment(),
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=240,
                check=False,
            )
            code = result.returncode
        except subprocess.TimeoutExpired:
            log.write(b"\nSOURCE_SECURITY_TIMEOUT\n")
            code = 124
        except OSError:
            log.write(b"\nSOURCE_SECURITY_EXECUTION_UNAVAILABLE\n")
            code = 127
    return {
        "tool": tool,
        "command": command,
        "exit_code": code,
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
    }


def verify_scanner_python(path: Path, root: Path) -> None:
    require(
        path.is_absolute() and path.is_file() and os.access(path, os.X_OK),
        "scanner interpreter must be an absolute executable file",
    )
    require(
        not path.resolve().is_relative_to(root.resolve()), "scanner environment is inside source"
    )
    result = subprocess.run(
        [str(path), "-I", "-m", "pip_audit", "--version"],
        env=_environment(),
        capture_output=True,
        check=True,
        timeout=30,
    )
    require(
        result.stdout.decode().strip() == f"pip-audit {PIP_AUDIT_VERSION}",
        "wrong pip-audit version",
    )


def _outputs(output: Path) -> dict[str, bytes]:
    members = {}
    for name in OUTPUT_MEMBERS:
        path = output / name
        require(path.is_file() and not path.is_symlink(), f"missing native scanner output: {name}")
        members[name] = path.read_bytes()
    return members


def _scan(
    root: Path, scanner_python: Path, output: Path, temporary: Path, receipt: dict[str, Any]
) -> None:
    verify_scanner_python(scanner_python, root)
    require(trusted_executable("/usr/bin/docker") is not None, "trusted Docker CLI unavailable")
    before, files = admit_source(root)
    receipt.update(before)
    receipt["tools"] = expected_tools(root)
    source = temporary / "source"
    freeze_source(source, files)
    require(
        snapshot(source, SOURCE_INPUTS) == before["source_before"],
        "source snapshot differs from the frozen export",
    )
    (temporary / "docker-config").mkdir()
    write_json(output / "lock-sbom.cdx.json", build_lock_sbom(source))
    commands = scanner_commands(
        root, source, output, temporary, scanner_python, before["source_commit_sha"]
    )
    receipt["executions"] = [
        execute(name, commands[name], output, source) for name in EXECUTION_NAMES
    ]
    verify_frozen_source(source, files)
    receipt["source_after_sha256"] = verify_source_after(root, before, files)
    members = _outputs(output)
    receipt["artifacts"] = {
        name: {"path": f"var/source-security/{name}", "sha256": hashlib.sha256(raw).hexdigest()}
        for name, raw in members.items()
    }
    require(
        all(
            type(item["exit_code"]) is int and item["exit_code"] == 0
            for item in receipt["executions"]
        ),
        "a required scanner did not succeed",
    )
    validate_outputs(members, source)
    receipt["status"] = "PASS"


def produce(root: Path, scanner_python: Path) -> dict[str, Any]:
    output = root / "var/source-security"
    output.mkdir(parents=True, exist_ok=False)
    receipt: dict[str, Any] = {"schema": SCHEMA, "status": "FAIL", "production_authorized": False}
    try:
        with TemporaryDirectory(
            prefix="korpus-source-security-", dir=runner_temporary(root)
        ) as directory:
            _scan(root, scanner_python, output, Path(directory), receipt)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
    write_json(output / "source-security-receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scanner-python", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = produce(ROOT, args.scanner_python)
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}))
        return 1
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": "var/source-security/source-security-receipt.json",
                "production_authorized": False,
            }
        )
    )
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
