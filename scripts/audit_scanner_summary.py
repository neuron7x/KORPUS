"""Validate scanner verdict semantics and bind them to the current source tree."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from source_digest import source_tree_digest

EXPECTED_SCANNERS = frozenset({"gitleaks", "pip-audit:runtime", "pip-audit:dev", "trivy"})
CI_CHECKS = frozenset(
    {"marker_shapes", "scanner_set_exact", "all_scanners_zero", "single_commit", "current_commit"}
)


@dataclass(frozen=True)
class SecuritySummaryBinding:
    commit_sha: str
    source_tree_sha256: str
    scanner_count: int

    @property
    def metadata(self) -> dict[str, str | int]:
        return {
            "security_summary_commit": self.commit_sha,
            "security_summary_source_tree_sha256": self.source_tree_sha256,
            "security_summary_scanners": self.scanner_count,
        }


def _summary_shape_problems(payload: dict[str, Any], expected_class: str) -> list[str]:
    problems: list[str] = []
    if expected_class == "LOCAL_SCANNERS":
        if payload.get("schema_version") != 1 or payload.get("class") != expected_class:
            problems.append("local scanner summary has the wrong schema or evidence class")
    elif expected_class == "PINNED_CI_SCANNERS":
        checks = payload.get("checks")
        if payload.get("schema_version") != 2:
            problems.append("CI scanner summary has the wrong schema")
        if (
            not isinstance(checks, dict)
            or set(checks) != CI_CHECKS
            or not all(value is True for value in checks.values())
        ):
            problems.append("CI scanner summary does not carry every successful aggregation check")
        if payload.get("failures") != []:
            problems.append("CI scanner summary carries aggregation failures")
    else:
        problems.append(f"unknown scanner evidence class: {expected_class}")
    return problems


def _scanner_result_problems(payload: dict[str, Any]) -> tuple[list[str], int]:
    records = payload.get("scanners")
    if not isinstance(records, list):
        return ["scanner results are not a list"], 0
    names = [item.get("scanner") for item in records if isinstance(item, dict)]
    exits = [item.get("exit_code") for item in records if isinstance(item, dict)]
    problems: list[str] = []
    if len(records) != len(EXPECTED_SCANNERS) or set(names) != EXPECTED_SCANNERS:
        problems.append("scanner set is incomplete, duplicated, or unexpected")
    if len(exits) != len(records) or any(
        not isinstance(code, int) or isinstance(code, bool) or code != 0 for code in exits
    ):
        problems.append("at least one scanner did not execute successfully")
    if payload.get("worst_exit_code") != 0 or payload.get("status") != "PASS":
        problems.append("scanner summary verdict is not PASS with worst exit code zero")
    return problems, len(records)


def validate_security_summary(
    root: Path, relative_path: str, expected_class: str
) -> SecuritySummaryBinding:
    """A named evidence class is insufficient until its verdict and subject are checked."""
    path = (root / relative_path).resolve()
    if root.resolve() not in path.parents:
        raise RuntimeError(f"unsafe scanner summary path: {relative_path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"scanner summary is unreadable: {relative_path}: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"scanner summary is not an object: {relative_path}")
    problems = _summary_shape_problems(payload, expected_class)
    scanner_problems, scanner_count = _scanner_result_problems(payload)
    problems.extend(scanner_problems)
    commit_value = payload.get("commit_sha")
    commit = (
        commit_value
        if isinstance(commit_value, str) and re.fullmatch(r"[0-9a-f]{40}", commit_value)
        else ""
    )
    scanned_digest = ""
    if not commit:
        problems.append("scanner summary has no canonical commit SHA")
    else:
        try:
            scanned_digest = source_tree_digest(commit)
            if scanned_digest != source_tree_digest("HEAD"):
                problems.append("scanner summary was produced from a different source tree")
        except (OSError, RuntimeError, subprocess.CalledProcessError):
            problems.append("scanner summary commit cannot be bound to the repository")
    if problems:
        raise RuntimeError("invalid scanner evidence: " + "; ".join(problems))
    return SecuritySummaryBinding(commit, scanned_digest, scanner_count)


def validate_selected_security_summary(root: Path, selection: Any) -> SecuritySummaryBinding:
    return validate_security_summary(
        root, str(selection.security_summary), str(selection.security_summary_class)
    )
