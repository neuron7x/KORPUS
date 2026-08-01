#!/usr/bin/env python3
"""Reject stale, incomplete, or source-mismatched release evidence."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from source_digest import source_tree_digest

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    failures: list[str] = []
    assurance_path = REPORTS / "RESEARCH_ASSURANCE_REPORT.json"
    snapshot_path = REPORTS / "ASSURANCE_SNAPSHOT.json"
    if not assurance_path.is_file() or not snapshot_path.is_file():
        raise SystemExit("release evidence is missing")
    assurance = json.loads(assurance_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    expected_release = os.getenv("KORPUS_RELEASE_VERSION", "v4.0.0")
    if assurance.get("status") != "PASS":
        failures.append("assurance status is not PASS")
    actual_digest = source_tree_digest("HEAD")
    if assurance.get("source_tree_sha256") != actual_digest:
        failures.append("assurance source digest does not match committed HEAD")
    if snapshot.get("status") != "PASS" or snapshot.get("release") != expected_release:
        failures.append("assurance snapshot release/status mismatch")
    for record in snapshot.get("records", []):
        path = ROOT / str(record.get("path", ""))
        if not path.is_file() or path.stat().st_size != record.get("bytes") or sha256(path) != record.get("sha256"):
            failures.append(f"snapshot record mismatch: {record.get('path')}")
    if failures:
        print(json.dumps({"valid": False, "failures": failures}, indent=2))
        return 1
    print(json.dumps({"valid": True, "release": expected_release, "source_tree_sha256": actual_digest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
