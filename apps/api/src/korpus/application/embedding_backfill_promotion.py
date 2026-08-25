"""Fail-closed promotion projection for a completed embedding reconciliation."""

from __future__ import annotations

from korpus.application.embedding_backfill_run import BackfillRunReceipt
from korpus.application.embedding_coverage import EmbeddingCoverage


def finalize_backfill_report(
    receipt: BackfillRunReceipt,
    coverage: EmbeddingCoverage,
    metadata: dict[str, object],
) -> tuple[bool, dict[str, object]]:
    complete = receipt.complete and coverage.complete
    report = {
        **receipt.as_dict(),
        "status": "COMPLETE" if complete else "COVERAGE_INCOMPLETE",
        "complete": complete,
        "reconciliation_complete": receipt.complete,
        "coverage": coverage.as_dict(),
        **metadata,
    }
    return complete, report
