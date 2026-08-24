from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _records(value: Any) -> list[Mapping[str, Any]] | None:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        return None
    return list(value)


def _unique_nonempty_ids(records: Sequence[Mapping[str, Any]]) -> bool:
    ids = [str(item.get("id", "")).strip() for item in records]
    return bool(ids) and all(ids) and len(ids) == len(set(ids))


def _case_state(cases: list[Mapping[str, Any]] | None, required: set[str]) -> tuple[bool, set[str]]:
    if cases is None or not _unique_nonempty_ids(cases):
        return False, set()
    covered: set[str] = set()
    for case in cases:
        family = str(case.get("attack_family", ""))
        if family not in required:
            return False, covered
        covered.add(family)
    return True, covered


def _finding_state(
    findings: list[Mapping[str, Any]] | None,
    allowed_severities: set[str],
    allowed_statuses: set[str],
    blocking: set[str],
    blocking_allowed: set[str],
) -> tuple[bool, list[str]]:
    if findings is None:
        return False, []
    ids: list[str] = []
    blocking_open: list[str] = []
    for item in findings:
        finding_id = str(item.get("id", "")).strip()
        severity, status = str(item.get("severity", "")), str(item.get("status", ""))
        if not finding_id or severity not in allowed_severities or status not in allowed_statuses:
            return False, blocking_open
        ids.append(finding_id)
        if severity in blocking and status not in blocking_allowed:
            blocking_open.append(finding_id)
    return len(ids) == len(set(ids)), blocking_open


def evaluate_external_redteam(
    report: Mapping[str, Any], profile: Mapping[str, Any]
) -> dict[str, Any]:
    required = {str(item) for item in profile.get("required_attack_families", ())}
    cases, findings = _records(report.get("test_cases")), _records(report.get("findings"))
    cases_valid, covered = _case_state(cases, required)
    findings_valid, blocking_open = _finding_state(
        findings,
        {str(item) for item in profile.get("allowed_finding_severities", ())},
        {str(item) for item in profile.get("allowed_finding_statuses", ())},
        {str(item) for item in profile.get("blocking_severities", ())},
        {str(item) for item in profile.get("blocking_finding_allowed_statuses", ())},
    )
    checks = {
        "test_cases_structured": cases_valid,
        "required_attack_families_covered": bool(required) and required.issubset(covered),
        "findings_structured": findings_valid,
        "blocking_findings_closed": findings_valid and not blocking_open,
    }
    recomputed = all(checks.values())
    checks["declared_status_consistent"] = report.get("status") == (
        "PASS" if recomputed else "FAIL"
    )
    return {
        "checks": checks,
        "pass": all(checks.values()),
        "required_attack_families": sorted(required),
        "covered_attack_families": sorted(covered),
        "test_cases": len(cases or ()),
        "findings": len(findings or ()),
        "blocking_open": blocking_open,
    }
