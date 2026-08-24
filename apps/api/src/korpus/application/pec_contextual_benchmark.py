"""Independent paired benchmark for deterministic contextual retrieval projections.

The benchmark never treats contextual text as evidence. It evaluates only whether the
retrieval-only projection improves the location/rank of already-judged gold evidence
without losing a baseline hit or weakening source binding.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Iterable, Mapping

from korpus.application.numeric_contracts import require_count, strict_int
from korpus.application.pec_statistics import paired_direction


def _required_bool(row: Mapping[str, object], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be boolean")
    return value


def _rank(row: Mapping[str, object], prefix: str) -> float:
    hit = _required_bool(row, f"{prefix}_hit")
    value = row.get(f"{prefix}_rank")
    if not hit:
        return float("inf")
    if not strict_int(value) or value < 1:
        raise ValueError(f"{prefix}_rank must be a positive integer when hit=true")
    return float(value)


def evaluate_contextual_benchmark(
    rows: Iterable[Mapping[str, object]], *, minimum_informative_pairs: int
) -> dict[str, object]:
    require_count(
        minimum_informative_pairs, positive=True, label="minimum_informative_pairs"
    )
    data = list(rows)
    issues: list[str] = []
    baseline: list[float] = []
    contextual: list[float] = []
    for row in data:
        query_id = str(row.get("query_id", ""))
        if not query_id:
            issues.append("missing_query_id")
        try:
            evidence_unchanged = _required_bool(row, "evidence_unchanged")
            citations_source_bound = _required_bool(row, "citations_source_bound")
            base_hit = _required_bool(row, "baseline_hit")
            context_hit = _required_bool(row, "contextual_hit")
        except ValueError as exc:
            issues.append(f"invalid_boolean:{query_id}:{exc}")
            # Fail closed while keeping the benchmark report materializable.
            baseline.append(float("inf"))
            contextual.append(float("inf"))
            continue
        if not evidence_unchanged:
            issues.append(f"evidence_changed:{query_id}")
        if not citations_source_bound:
            issues.append(f"source_binding_lost:{query_id}")
        if base_hit and not context_hit:
            issues.append(f"baseline_gold_hit_lost:{query_id}")
        baseline.append(_rank(row, "baseline"))
        contextual.append(_rank(row, "contextual"))
    comparison = paired_direction(contextual, baseline)
    supported = (
        comparison.informative_pairs >= minimum_informative_pairs
        and comparison.lower_win_probability > 0.5
    )
    status = "FAIL" if issues else ("PASS" if supported else "UNKNOWN")
    return {
        "status": status,
        "rows": len(data),
        "minimum_informative_pairs": minimum_informative_pairs,
        "rank_comparison": asdict(comparison),
        "confidence_supported_improvement": supported,
        "issues": issues,
    }
