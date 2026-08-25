"""Fail-closed promotion projection for a completed embedding reconciliation."""

from __future__ import annotations

import hashlib
import json

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
    canonical = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    report["receipt_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return complete, report
