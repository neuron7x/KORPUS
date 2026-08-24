"""Discrete-domain invariants for embedding coverage and migrations."""
from __future__ import annotations

from korpus.application.numeric_contracts import strict_int


def counters_within_total(total: object, *counts: object) -> bool:
    return strict_int(total) and total >= 0 and all(strict_int(v) and 0 <= v <= total for v in counts)


def validate_embedding_coverage(model_id: str, dimensions: object, total: object, active: object, other: object, stale: object) -> None:
    if not model_id.strip():
        raise ValueError("active_model_id must be non-empty")
    if not strict_int(dimensions) or dimensions < 8:
        raise ValueError("active_dimensions must be an integer of at least 8")
    if not counters_within_total(total, active, other, stale):
        raise ValueError("embedding coverage counters must be non-negative integers bounded by total spans")
