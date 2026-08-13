#!/usr/bin/env python3
"""Reject stale, incomplete, or source-mismatched release evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path

from evidence_source_binding import committed_evidence_source_digest
from release_identity import release_tag
from research_assurance_verification import verify_research_assurance
from source_digest import source_tree_digest

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    expected_release = os.getenv("KORPUS_RELEASE_VERSION", release_tag())
    source_digest = source_tree_digest("HEAD")
    try:
        evidence_digest = committed_evidence_source_digest()
    except RuntimeError:
        evidence_digest = None
    failures = verify_research_assurance(
        ROOT,
        expected_release,
        source_tree_sha256=source_digest,
        evidence_source_sha256=evidence_digest,
        binding="committed HEAD",
    )
    if failures:
        print(json.dumps({"valid": False, "failures": failures}, indent=2))
        return 1
    summary = {"valid": True, "release": expected_release, "source_tree_sha256": source_digest}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
