"""Explicit post-baseline source history eligible for empty-database bootstrap."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from korpus.infrastructure.migration_baseline_proof import (
    BaselineProof,
    verify_baseline,
    verify_passive_revision,
)

BOOTSTRAP_REVISIONS = (
    "0025_sealed_provenance_integrity",
    "0026_learning_history_integrity",
    "0027_learning_competency_integrity",
    "0028_reviewer_update_scope",
)
BOOTSTRAP_HEAD = BOOTSTRAP_REVISIONS[-1]


class MigrationAdmissionError(RuntimeError):
    """No observed state proves this migration is admissible."""


def preflight_source(source_root: Path) -> BaselineProof:
    """Capture only the explicit passive chain; this does not admit a populated upgrade."""
    baseline = verify_baseline(source_root)
    files = list((source_root / "apps/api/migrations/versions").glob("*.py"))
    actual = {str(path.relative_to(source_root)) for path in files}
    expected = baseline.files | {
        f"apps/api/migrations/versions/{revision}.py" for revision in BOOTSTRAP_REVISIONS
    }
    if any(path.is_symlink() for path in files) or actual != expected:
        raise MigrationAdmissionError("DENIED_SOURCE_HISTORY_UNPROVEN")
    sources = list(baseline.sources)
    parents = (baseline.chain[-1], *BOOTSTRAP_REVISIONS[:-1])
    for revision, parent in zip(BOOTSTRAP_REVISIONS, parents, strict=True):
        sources.append(verify_passive_revision(source_root, revision, parent))
    return replace(baseline, sources=tuple(sources))
