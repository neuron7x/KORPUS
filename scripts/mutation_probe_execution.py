"""Measured pytest outcomes for mutation probes; infrastructure failure is not a kill."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from bounded_process import run_bounded


@dataclass(frozen=True)
class SuiteExecution:
    status: Literal["PASSED", "FAILED", "INCONCLUSIVE"]
    reason: str
    seconds: float
    returncode: int | None
    identities: tuple[str, ...] = ()
    skipped_ids: tuple[str, ...] = ()
    failures: int = 0
    errors: int = 0
    output_tail: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""

    def receipt(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "seconds": round(self.seconds, 3),
            "returncode": self.returncode,
            "tests": len(self.identities),
            "failures": self.failures,
            "errors": self.errors,
            "skipped": len(self.skipped_ids),
            "node_sha256": hashlib.sha256(json.dumps(self.identities).encode()).hexdigest(),
            "output_tail": self.output_tail,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
        }


def _junit_receipt(path: Path, returncode: int, seconds: float, output: str) -> SuiteExecution:
    try:
        cases = list(ET.parse(path).getroot().iter("testcase"))
    except (ET.ParseError, OSError):
        return SuiteExecution("INCONCLUSIVE", "JUNIT_UNAVAILABLE", seconds, returncode)
    identities = tuple(f"{c.get('classname', '')}::{c.get('name', '')}" for c in cases)
    skipped = tuple(
        identity
        for identity, case in zip(identities, cases, strict=True)
        if case.find("skipped") is not None
    )
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    status, reason = _classify_receipt(returncode, identities, skipped, failures, errors)
    return SuiteExecution(
        status, reason, seconds, returncode, identities, skipped, failures, errors, output[-3000:]
    )


def _classify_receipt(
    returncode: int,
    identities: tuple[str, ...],
    skipped: tuple[str, ...],
    failures: int,
    errors: int,
) -> tuple[Literal["PASSED", "FAILED", "INCONCLUSIVE"], str]:
    if not identities or len(identities) == len(skipped):
        return "INCONCLUSIVE", "NO_EXECUTED_TESTS"
    if len(set(identities)) != len(identities):
        return "INCONCLUSIVE", "DUPLICATE_TEST_IDENTITY"
    if errors:
        return "INCONCLUSIVE", "PYTEST_ERRORS"
    if returncode == 0 and failures == 0:
        return "PASSED", "COMPLETED"
    if returncode == 1 and failures > 0:
        return "FAILED", "TEST_FAILURE"
    return "INCONCLUSIVE", "EXIT_RECEIPT_MISMATCH"


def run_suite(
    timeout_seconds: float,
    workspace: Path,
    *,
    test_paths: tuple[str, ...] | None = None,
    stop_on_failure: bool = True,
) -> SuiteExecution:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        return SuiteExecution("INCONCLUSIVE", "INVALID_TIMEOUT", 0.0, None)
    if test_paths == ():
        return SuiteExecution("INCONCLUSIVE", "NO_SELECTED_TESTS", 0.0, None)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="korpus-probe-junit-") as temporary:
        report = Path(temporary) / "pytest.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            *(test_paths if test_paths is not None else ("apps/api/tests",)),
            "-x" if stop_on_failure else "--maxfail=0",
            "-q",
            "--no-cov",
            "-p",
            "no:cacheprovider",
            f"--junitxml={report}",
        ]
        environment = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(workspace / "apps/api/src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        }
        code, stdout, stderr, timed_out, termination = run_bounded(
            command, cwd=workspace, env=environment, timeout_seconds=timeout_seconds
        )
        elapsed, output = time.monotonic() - started, stdout + "\n" + stderr
        if timed_out or code is None:
            execution = SuiteExecution(
                "INCONCLUSIVE",
                f"{'TIMEOUT' if timed_out else 'EXECUTION'}:{termination}",
                elapsed,
                code,
                output_tail=output[-3000:],
            )
        elif code not in (0, 1):
            execution = SuiteExecution(
                "INCONCLUSIVE", f"PYTEST_EXIT_{code}", elapsed, code, output_tail=output[-3000:]
            )
        else:
            execution = _junit_receipt(report, code, elapsed, output)
        return replace(execution, stdout_tail=stdout[-1500:], stderr_tail=stderr[-1000:])


def mutation_outcome(
    baseline: SuiteExecution, execution: SuiteExecution, *, require_complete: bool = False
) -> tuple[str, str]:
    if baseline.status != "PASSED" or execution.status == "INCONCLUSIVE":
        return "INCONCLUSIVE", execution.reason
    if not set(execution.identities) <= set(baseline.identities):
        return "INCONCLUSIVE", "UNEXPECTED_TEST_IDENTITIES"
    if not set(execution.skipped_ids) <= set(baseline.skipped_ids):
        return "INCONCLUSIVE", "NEW_SKIPPED_TESTS"
    if require_complete and set(execution.identities) != set(baseline.identities):
        return "INCONCLUSIVE", "MISSING_TEST_IDENTITIES"
    if require_complete and set(execution.skipped_ids) != set(baseline.skipped_ids):
        return "INCONCLUSIVE", "CHANGED_TEST_EXECUTION"
    if execution.status == "FAILED":
        return "KILLED", "TEST_FAILURE"
    if set(execution.identities) != set(baseline.identities):
        return "INCONCLUSIVE", "MISSING_TEST_IDENTITIES"
    if set(execution.skipped_ids) != set(baseline.skipped_ids):
        return "INCONCLUSIVE", "CHANGED_TEST_EXECUTION"
    return "SURVIVED", "COMPLETED"
