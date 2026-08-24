"""Pure paired ablation policy for PEC promotion evidence."""
from __future__ import annotations

from korpus.application.numeric_contracts import finite_number, require_count
from korpus.application.pec_replay import RESOURCE_FIELDS
from korpus.application.pec_statistics import paired_direction


def _bool(row: dict[str, object], key: str) -> bool:
    if key not in row or not isinstance(row[key], bool):
        raise ValueError(f"ablation row missing boolean {key}")
    return row[key]


def _number(row: dict[str, object], key: str) -> float:
    value = row.get(key)
    if not finite_number(value):
        raise ValueError(f"ablation row missing finite numeric {key}")
    number = float(value)
    if number < 0.0:
        raise ValueError(f"ablation resource {key} must be non-negative")
    return number


def regressions(
    ids: list[str], baseline: dict[str, dict[str, object]], candidate: dict[str, dict[str, object]]
) -> tuple[int, int]:
    safety = sum(
        _bool(baseline[q], "authorization_ok") and not _bool(candidate[q], "authorization_ok")
        for q in ids
    ) + sum(
        not _bool(baseline[q], "answer_error") and _bool(candidate[q], "answer_error")
        for q in ids
    )
    quality = sum(
        _bool(baseline[q], "quality_ok") and not _bool(candidate[q], "quality_ok")
        for q in ids
    )
    return safety, quality


def resource_comparisons(
    ids: list[str], baseline: dict[str, dict[str, object]], candidate: dict[str, dict[str, object]],
    minimum_pairs: int,
) -> tuple[dict[str, object], bool]:
    resources: dict[str, object] = {}
    supported_improvement = False
    for field in RESOURCE_FIELDS:
        comparison = paired_direction(
            [_number(candidate[q], field) for q in ids],
            [_number(baseline[q], field) for q in ids],
        )
        supported = comparison.informative_pairs >= minimum_pairs and comparison.lower_win_probability > 0.5
        supported_improvement = supported_improvement or supported
        resources[field] = {
            "wins": comparison.wins, "losses": comparison.losses, "ties": comparison.ties,
            "informative_pairs": comparison.informative_pairs,
            "win_probability_interval_95": [comparison.lower_win_probability, comparison.upper_win_probability],
            "confidence_supported_improvement": supported,
        }
    return resources, supported_improvement


def compare_ablation(
    baseline: dict[str, dict[str, object]], candidate: dict[str, dict[str, object]], *, minimum_pairs: int
) -> dict[str, object]:
    require_count(minimum_pairs, positive=True, label="minimum_pairs")
    if set(candidate) != set(baseline):
        return {"status": "FAIL", "reason": "query_set_mismatch"}
    ids = sorted(baseline)
    safety_regressions, quality_regressions = regressions(ids, baseline, candidate)
    resources, supported_improvement = resource_comparisons(ids, baseline, candidate, minimum_pairs)
    status = (
        "FAIL" if safety_regressions or quality_regressions
        else "PASS" if supported_improvement
        else "UNKNOWN"
    )
    return {
        "status": status, "queries": len(ids),
        "safety_regressions": safety_regressions, "quality_regressions": quality_regressions,
        "confidence_supported_efficiency_improvement": supported_improvement,
        "resources": resources,
    }
