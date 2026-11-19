"""The publisher invokes live admission once; environment values are selectors only."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from github_evidence_import import fetch_evidence
from github_evidence_run import Selection
from github_evidence_transport import insist, strict_object

SELECTOR_FIELDS = ("KORPUS_EVIDENCE_RUN_ID", "KORPUS_EVIDENCE_RUN_ATTEMPT", "KORPUS_EVIDENCE_REF")


def admitted_coverage_projection(root: Path, identity: tuple[str, str]) -> dict[str, Any] | None:
    values = [os.environ.get(name, "") for name in SELECTOR_FIELDS]
    if not any(values):
        return None
    insist(
        all(values), "hosted evidence publication requires all explicit run/attempt/ref selectors"
    )
    insist(
        all(value.isascii() and value.isdecimal() for value in values[:2]), "invalid run selectors"
    )
    evidence = fetch_evidence(root, Selection(int(values[0]), int(values[1]), values[2]))
    digest, release = identity
    insist(
        evidence.identity.evidence_source_sha256 == digest,
        "publisher source digest conflicts with admitted source",
    )
    declared = strict_object(
        evidence.source_members["apps/api/src/korpus/release.json"], "captured release identity"
    )
    insist(declared.get("tag") == release, "publisher release conflicts with checked-out identity")
    return evidence.coverage_projection(release)
