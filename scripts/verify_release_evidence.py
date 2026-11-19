#!/usr/bin/env python3
"""Reject stale, incomplete, or source-mismatched release evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path

from evidence_source_binding import evidence_source_binding_failure
from release_identity import release_tag
from research_assurance_verification import research_assurance_failures
from snapshot_assurance import complete_snapshot_records, load_json
from source_digest import source_tree_digest

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
REPORT_NAMES = ("RESEARCH_ASSURANCE_REPORT.json", "ASSURANCE_SNAPSHOT.json")


def main() -> int:
    assurance_path, snapshot_path = (REPORTS / name for name in REPORT_NAMES)
    if not assurance_path.is_file() or not snapshot_path.is_file():
        raise SystemExit("release evidence is missing")
    assurance = load_json(assurance_path)
    snapshot = load_json(snapshot_path)
    expected_release = os.getenv("KORPUS_RELEASE_VERSION", release_tag())
    actual_digest = source_tree_digest("HEAD")
    binding_failure = evidence_source_binding_failure(assurance.get("evidence_source_sha256"))
    failures = research_assurance_failures(
        assurance,
        snapshot,
        expected_release,
        actual_digest,
        binding_failure,
        bool(complete_snapshot_records(snapshot.get("records"))),
        "committed HEAD",
    )
    if failures:
        print(json.dumps({"valid": False, "failures": failures}, indent=2))
        return 1
    summary = {"valid": True, "release": expected_release, "source_tree_sha256": actual_digest}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
