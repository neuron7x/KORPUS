"""Bind assurance artifacts to the source tree that produced them.

A gate that accepts a report without asking which tree produced it cannot fail:
evidence from another checkout, or evidence from yesterday's code, both read as
PASS. The destruction stage of 2026-08-03 demonstrated exactly that — the
operational gate returned PASS for artifacts stamped ``source_commit='0'*40``.

The binding here is over content, not a commit id. Evidence is commonly generated
from a working tree before commit, so every report is stamped with a digest of the
source surfaces that can change assurance results. Release tooling separately binds
that digest to the committed source bytes that packaging ships.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from korpus.application.evidence_digest import EVIDENCE_SOURCE_PATHS, compute_source_digest

PROVENANCE_KEY = "provenance"
PROVENANCE_SCHEMA_VERSION = 1


class ProvenanceError(ValueError):
    """Raised when an artifact cannot be bound to a source tree."""


@dataclass(frozen=True)
class SourceProvenance:
    """The tree an artifact claims to describe."""

    source_digest: str
    generator: str
    generated_at: str
    schema_version: int = PROVENANCE_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "generator": self.generator,
            "generated_at": self.generated_at,
        }


def stamp(root: Path, generator: str) -> dict[str, Any]:
    """Build the provenance block an assurance generator must embed."""

    if not generator:
        raise ProvenanceError("generator name is required")
    return SourceProvenance(
        source_digest=compute_source_digest(root),
        generator=generator,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    ).as_dict()


def read_provenance(report: Mapping[str, Any]) -> SourceProvenance:
    """Extract provenance from a report, refusing anything malformed."""

    block = report.get(PROVENANCE_KEY)
    if not isinstance(block, Mapping):
        raise ProvenanceError("report carries no provenance block")
    if int(block.get("schema_version", 0)) != PROVENANCE_SCHEMA_VERSION:
        raise ProvenanceError("unsupported provenance schema")
    digest = block.get("source_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ProvenanceError("provenance source_digest is missing or malformed")
    generator = block.get("generator")
    generated_at = block.get("generated_at")
    if not isinstance(generator, str) or not generator:
        raise ProvenanceError("provenance generator is missing")
    if not isinstance(generated_at, str) or not generated_at:
        raise ProvenanceError("provenance generated_at is missing")
    return SourceProvenance(
        source_digest=digest,
        generator=generator,
        generated_at=generated_at,
        schema_version=PROVENANCE_SCHEMA_VERSION,
    )


def verify_reports(
    reports: Mapping[str, Mapping[str, Any]], expected_digest: str
) -> tuple[bool, tuple[str, ...]]:
    """Check every report against the digest recomputed from the live tree."""

    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        return False, ("expected source digest is missing or malformed",)
    reasons: list[str] = []
    for name in sorted(reports):
        try:
            provenance = read_provenance(reports[name])
        except ProvenanceError as error:
            reasons.append(f"{name}: {error}")
            continue
        if provenance.source_digest != expected_digest:
            reasons.append(
                f"{name}: generated from a different source tree "
                f"({provenance.source_digest[:12]}… != {expected_digest[:12]}…)"
            )
    return not reasons, tuple(reasons)
