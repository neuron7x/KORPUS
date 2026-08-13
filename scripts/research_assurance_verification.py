"""Verify research assurance against an explicit source state and snapshot."""
from __future__ import annotations

import json
from pathlib import Path

from assurance_snapshot_verification import verify_assurance_snapshot

REPORT_PATH = "reports/RESEARCH_ASSURANCE_REPORT.json"


def _valid_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def verify_research_assurance(
    root: Path,
    expected_release: str,
    *,
    source_tree_sha256: str,
    evidence_source_sha256: str | None,
    binding: str,
) -> list[str]:
    path = root / REPORT_PATH
    if not path.is_file():
        return ["research assurance report is missing"]
    try:
        assurance = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["research assurance report is unreadable or invalid JSON"]
    if not isinstance(assurance, dict):
        return ["research assurance report is not an object"]

    failures: list[str] = []
    if assurance.get("status") != "PASS":
        failures.append("assurance status is not PASS")
    if assurance.get("source_tree_sha256") != source_tree_sha256:
        failures.append(f"assurance source digest does not match {binding}")
    claimed_evidence = assurance.get("evidence_source_sha256")
    if not _valid_sha256(claimed_evidence):
        failures.append("assurance evidence source digest is missing or malformed")
    elif evidence_source_sha256 is None:
        failures.append(f"assurance evidence source digest cannot be verified against {binding}")
    elif claimed_evidence.lower() != evidence_source_sha256:
        failures.append(f"assurance evidence source digest does not match {binding}")
    failures.extend(verify_assurance_snapshot(root, expected_release))
    return failures
