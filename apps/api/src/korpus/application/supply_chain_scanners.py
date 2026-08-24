from __future__ import annotations

from collections.abc import Mapping
from typing import Any

EXPECTED_SECURITY_SCANNERS = frozenset({"gitleaks", "pip-audit:runtime", "pip-audit:dev", "trivy"})
EXPECTED_CONTAINER_SCANNERS = frozenset({"trivy:api-image", "trivy:web-image"})


def _scanner_marker_clean(scan: Mapping[str, Any], expected: frozenset[str]) -> bool:
    records = scan.get("scanners", ())
    if not isinstance(records, list):
        return False
    parsed = {
        str(item.get("scanner")): item.get("exit_code")
        for item in records if isinstance(item, Mapping)
    }
    return (
        scan.get("status") == "PASS"
        and scan.get("worst_exit_code") == 0
        and set(parsed) == expected
        and len(records) == len(expected)
        and all(parsed[name] == 0 for name in expected)
    )


def scanner_summary_clean(scan: Mapping[str, Any]) -> bool:
    return _scanner_marker_clean(scan, EXPECTED_SECURITY_SCANNERS)


def container_scan_marker_clean(scan: Mapping[str, Any]) -> bool:
    return _scanner_marker_clean(scan, EXPECTED_CONTAINER_SCANNERS)


def scanner_marker_current(scan: Mapping[str, Any], expected_commit: str) -> bool:
    return bool(expected_commit) and scan.get("commit_sha") == expected_commit
