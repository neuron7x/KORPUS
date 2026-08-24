"""Bind assurance artifacts to the source tree that produced them.

A gate that accepts a report without asking which tree produced it cannot fail:
evidence from another checkout, or evidence from yesterday's code, both read as
PASS. The destruction stage of 2026-08-03 demonstrated exactly that — the
operational gate returned PASS for artifacts stamped ``source_commit='0'*40``.

The binding here is over *content*, not over a commit id, for two reasons. A
commit id is a claim the producer writes about itself and nothing recomputes it;
and a working tree with uncommitted edits has no commit id at all, which is the
state in which most evidence is actually generated. The digest below is
recomputed by the verifier from the files on disk, so a stale or foreign report
cannot match unless the tree matches.

Executable behavior, public contracts, deployment behavior and release-control decisions are digested. Human documentation remains outside the boundary; frontend source, API contracts, IaC/deployment manifests and CI/release orchestration are inside it so stale evidence cannot survive a shipped-system or gate-graph change.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROVENANCE_KEY = "provenance"
PROVENANCE_SCHEMA_VERSION = 1

from korpus.application.provenance_surface import (
    EVIDENCE_SOURCE_PATHS,
    EXCLUDED_DIRECTORY_NAMES as _EXCLUDED_DIRECTORY_NAMES,
    EXCLUDED_SUFFIXES as _EXCLUDED_SUFFIXES,
)


class ProvenanceError(ValueError):
    """Raised when an artifact cannot be bound to a source tree."""


def _digest_candidates(root: Path, sources: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for relative in sources:
        target = root / relative
        if target.is_file():
            files.append(target)
            continue
        if not target.is_dir():
            # A declared source that does not exist is not an error: the set is
            # shared by both the API tree and the packaged distribution, and a
            # missing optional lock file must not change the digest silently
            # into an exception at gate time.
            continue
        for path in target.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _EXCLUDED_DIRECTORY_NAMES for part in path.relative_to(root).parts):
                continue
            if path.suffix in _EXCLUDED_SUFFIXES:
                continue
            files.append(path)
    return sorted(set(files), key=lambda path: path.relative_to(root).as_posix())


def compute_source_digest(
    root: Path, sources: Iterable[str] = EVIDENCE_SOURCE_PATHS
) -> str:
    """Digest the evidence-bearing source surface of a working tree.

    Length-prefixed path and content are both fed to the hash so that moving a
    byte from a file name into its content cannot produce the same digest.
    """

    hasher = hashlib.sha256()
    hasher.update(b"korpus-source-digest-v2\0")
    for path in _digest_candidates(root, sources):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        hasher.update(len(relative).to_bytes(4, "big"))
        hasher.update(relative)
        with path.open("rb") as handle:
            expected_size = path.stat().st_size
            hasher.update(expected_size.to_bytes(8, "big"))
            observed_size = 0
            while chunk := handle.read(1024 * 1024):
                observed_size += len(chunk)
                hasher.update(chunk)
        if observed_size != expected_size:
            raise ProvenanceError(f"source changed while hashing: {path}")
    return hasher.hexdigest()


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
    if (type(block.get("schema_version")), block.get("schema_version")) != (int, PROVENANCE_SCHEMA_VERSION):
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
    """Check every report against the digest recomputed from the live tree.

    Returns (ok, reasons). Absence of provenance is a failure, not a skip: a
    report that does not say which tree it came from is exactly the artifact the
    check exists to reject.
    """

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
