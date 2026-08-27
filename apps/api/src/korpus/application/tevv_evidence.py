"""Recompute production TEVV aggregates from a signed case ledger."""

from __future__ import annotations

from collections import Counter
from typing import Any

_COUNT_FIELDS = ("citation_failures", "leakage_failures", "determinism_failures")


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _families(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result = [item for item in value if isinstance(item, str) and item]
    return result if len(result) == len(value) and len(set(result)) == len(result) else None


def _normalize_observations(value: object) -> tuple[list[dict[str, Any]], list[str], bool]:
    if not isinstance(value, list) or not value:
        return [], [], False
    rows: list[dict[str, Any]] = []
    ids: list[str] = []
    structured = True
    for candidate in value:
        if not isinstance(candidate, dict):
            structured = False
            continue
        case_id, passed = candidate.get("id"), candidate.get("passed")
        families = _families(candidate.get("attack_families"))
        cohorts = _families(candidate.get("cohorts"))
        if not (
            isinstance(case_id, str)
            and bool(case_id)
            and isinstance(passed, bool)
            and families is not None
            and cohorts is not None
            and all(_nonnegative_int(candidate.get(field)) for field in _COUNT_FIELDS)
        ):
            structured = False
            continue
        row = dict(candidate)
        row["attack_families"] = families
        row["cohorts"] = cohorts
        rows.append(row)
        ids.append(case_id)
    return rows, ids, structured and len(rows) == len(value)


def _normalize_nulls(value: object) -> tuple[list[dict[str, Any]], list[str], bool]:
    if not isinstance(value, list):
        return [], [], False
    rows: list[dict[str, Any]] = []
    ids: list[str] = []
    structured = True
    for candidate in value:
        if not isinstance(candidate, dict):
            structured = False
            continue
        control_id, false_accept = candidate.get("id"), candidate.get("false_accept")
        if not (isinstance(control_id, str) and control_id and isinstance(false_accept, bool)):
            structured = False
            continue
        rows.append(dict(candidate))
        ids.append(control_id)
    return rows, ids, structured and len(rows) == len(value)


def _metrics(observations: list[dict[str, Any]], nulls: list[dict[str, Any]]) -> dict[str, Any]:
    cohort_counts = Counter(cohort for row in observations for cohort in row["cohorts"])
    return {
        "observations": len(observations),
        "passed": sum(bool(row["passed"]) for row in observations),
        **{field: sum(int(row[field]) for row in observations) for field in _COUNT_FIELDS},
        "null_controls": len(nulls),
        "null_control_false_accepts": sum(bool(row["false_accept"]) for row in nulls),
        "attack_families": sorted(
            {family for row in observations for family in row["attack_families"]}
        ),
        "cohort_counts": dict(sorted(cohort_counts.items())),
    }


def _declared_consistent(evidence: dict[str, Any], metrics: dict[str, Any]) -> bool:
    return all(
        evidence.get(key) is None or evidence.get(key) == metrics[key]
        for key in (
            "observations",
            "passed",
            "citation_failures",
            "leakage_failures",
            "determinism_failures",
            "null_controls",
            "null_control_false_accepts",
            "attack_families",
            "cohort_counts",
        )
    )


def evaluate_tevv_ledger(evidence: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    observations, observation_ids, observations_ok = _normalize_observations(
        evidence.get("observation_ledger")
    )
    nulls, null_ids, nulls_ok = _normalize_nulls(evidence.get("null_control_ledger"))
    metrics = _metrics(observations, nulls)
    required = set(profile.get("required_attack_families", ()))
    required_cohorts = set(profile.get("required_cohorts", ()))
    minimum_cohort = profile.get("minimum_observations_per_required_cohort", 0)
    checks = {
        "observation_ledger_structured": observations_ok,
        "observation_ids_unique": len(observation_ids) == len(set(observation_ids)),
        "null_control_ledger_structured": nulls_ok,
        "null_control_ids_unique": len(null_ids) == len(set(null_ids)),
        "required_attack_families_covered": required.issubset(set(metrics["attack_families"])),
        "required_cohorts_covered": all(
            metrics["cohort_counts"].get(cohort, 0) >= minimum_cohort
            for cohort in required_cohorts
        ),
        "declared_aggregates_consistent": _declared_consistent(evidence, metrics),
    }
    return {"checks": checks, "metrics": metrics}
