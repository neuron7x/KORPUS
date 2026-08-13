#!/usr/bin/env python3
"""Reject stale, incomplete, or source-mismatched release evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path

from assurance_snapshot_verification import verify_assurance_snapshot
from evidence_source_binding import evidence_source_binding_failure
from release_identity import release_tag
from source_digest import source_tree_digest

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    failures: list[str] = []
    assurance_path = ROOT / "reports/RESEARCH_ASSURANCE_REPORT.json"
    if not assurance_path.is_file():
        raise SystemExit("release evidence is missing")
    assurance = json.loads(assurance_path.read_text(encoding="utf-8"))
    expected_release = os.getenv("KORPUS_RELEASE_VERSION", release_tag())
    if assurance.get("status") != "PASS":
        failures.append("assurance status is not PASS")
    actual_digest = source_tree_digest("HEAD")
    if assurance.get("source_tree_sha256") != actual_digest:
        failures.append("assurance source digest does not match committed HEAD")
    if binding_failure := evidence_source_binding_failure(assurance.get("evidence_source_sha256")):
        failures.append(binding_failure)
    failures.extend(verify_assurance_snapshot(ROOT, expected_release))
    if failures:
        print(json.dumps({"valid": False, "failures": failures}, indent=2))
        return 1
    summary = {"valid": True, "release": expected_release, "source_tree_sha256": actual_digest}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
