"""Numeric admissibility checks for recovery evidence."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from korpus.application.numeric_contracts import bounded_number, nonnegative_count

COUNT_FIELDS = ("backup_bytes", "plaintext_bytes", "document_rows", "audit_event_rows", "writes_after_backup")


def recovery_numeric_problem(report: Mapping[str, Any], provenance: Mapping[str, Any]) -> str | None:
    if bounded_number(report.get("rto_seconds"), 0, float("inf")) is None:
        return "recovery report has no finite non-negative rto_seconds"
    if bounded_number(report.get("rpo_seconds"), 0, float("inf")) is None:
        return "recovery report has no finite non-negative rpo_seconds"
    if nonnegative_count(report.get("lost_events"), allow_digit_string=True) is None:
        return "recovery report has no non-negative integer lost_events"
    invalid = [f for f in COUNT_FIELDS if nonnegative_count(provenance.get(f), allow_digit_string=True) is None]
    if invalid:
        return f"recovery provenance has invalid counts: {', '.join(sorted(invalid))}"
    if not nonnegative_count(provenance.get("writes_after_backup"), allow_digit_string=True):
        return "no writes were made after the backup, so the loss figure is trivially zero and the drill could not have come out any other way"
    return None


def recovery_scale_counts(provenance: Mapping[str, Any]) -> tuple[int, int]:
    return nonnegative_count(provenance.get("document_rows"), allow_digit_string=True) or 0, nonnegative_count(provenance.get("plaintext_bytes"), allow_digit_string=True) or 0
