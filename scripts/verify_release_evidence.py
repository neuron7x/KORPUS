#!/usr/bin/env python3
"""Reject stale, incomplete, or source-mismatched release evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from evidence_source_binding import evidence_source_binding_failure
from release_identity import release_tag
from source_digest import source_tree_digest

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
REPORT_NAMES = ("RESEARCH_ASSURANCE_REPORT.json", "ASSURANCE_SNAPSHOT.json")


def main() -> int:
    failures: list[str] = []
    assurance_path, snapshot_path = (REPORTS / name for name in REPORT_NAMES)
    if not assurance_path.is_file() or not snapshot_path.is_file():
        raise SystemExit("release evidence is missing")
    assurance = json.loads(assurance_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    expected_release = os.getenv("KORPUS_RELEASE_VERSION", release_tag())
    failures.extend(["assurance status is not PASS"] * (assurance.get("status") != "PASS"))
    actual_digest = source_tree_digest("HEAD")
    digest_matches = assurance.get("source_tree_sha256") == actual_digest
    failures += ["assurance source digest does not match committed HEAD"] * (not digest_matches)
    binding_failure = evidence_source_binding_failure(assurance.get("evidence_source_sha256"))
    failures.extend([str(binding_failure)] * (binding_failure is not None))
    if snapshot.get("status") != "PASS" or snapshot.get("release") != expected_release:
        failures.append("assurance snapshot release/status mismatch")
    for record in snapshot.get("records", []):
        path = ROOT / str(record.get("path", ""))
        if (
            not path.is_file()
            or path.stat().st_size != record.get("bytes")
            or hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256")
        ):
            failures.append(f"snapshot record mismatch: {record.get('path')}")
    if failures:
        print(json.dumps({"valid": False, "failures": failures}, indent=2))
        return 1
    summary = {"valid": True, "release": expected_release, "source_tree_sha256": actual_digest}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
