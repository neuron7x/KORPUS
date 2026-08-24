"""Evidence-bounded engineering readiness scoring.

This module is intentionally separate from production authorization.  The score is a
weighted maturity index over a preregistered profile.  Missing criteria count as zero;
source/release mismatch zeroes the whole dimension; evidence strength applies the same
ceilings as the canonical assurance calculus.  No score can turn a failed production
predicate into a PASS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from korpus.application.readiness_contracts import count_boolean_criteria, readiness_target
from korpus.application.assurance_calculus import (
    DimensionObservation,
    DimensionPolicy,
    EvidenceClass,
    EvidencePoint,
    ReadinessPolicy,
    evaluate_readiness,
)

_EVIDENCE_CLASS = {
    "NONE": EvidenceClass.NONE,
    "DECLARATIVE": EvidenceClass.DECLARATIVE,
    "STATIC": EvidenceClass.STATIC,
    "EXECUTED": EvidenceClass.EXECUTED,
    "EXECUTED_WITH_NEGATIVE_CONTROL": EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL,
    "INDEPENDENT_ATTESTED": EvidenceClass.INDEPENDENT_ATTESTED,
}


@dataclass(frozen=True, slots=True)
class CriterionResult:
    criterion_id: str
    passed: bool


@dataclass(frozen=True, slots=True)
class DimensionResult:
    dimension_id: str
    passed: int
    total: int
    raw_percent: float
    calibrated_percent: float


def _class(name: str) -> EvidenceClass:
    try:
        return _EVIDENCE_CLASS[name]
    except KeyError as exc:
        raise ValueError(f"unknown evidence class: {name}") from exc


def _evidence_point(
    class_name: str,
    *,
    source_digest: str,
    release: str,
    status: str = "PASS",
) -> EvidencePoint:
    cls = _class(class_name)
    independent = cls >= EvidenceClass.INDEPENDENT_ATTESTED
    return EvidencePoint(
        cls,
        source_digest,
        release,
        status,
        executed=cls >= EvidenceClass.EXECUTED,
        negative_control=cls >= EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL,
        independent=independent,
        attested=independent,
    )


def _criterion_summary(
    dimension_id: str,
    raw_policy: Mapping[str, Any],
    dimension_evidence: Mapping[str, Any],
) -> tuple[tuple[str, ...], int, int, float, str, EvidencePoint]:
    criterion_ids = tuple(str(item) for item in raw_policy.get("criteria", ()))
    if not criterion_ids or len(criterion_ids) != len(set(criterion_ids)):
        raise ValueError(f"dimension {dimension_id} criteria must be non-empty and unique")
    criteria_results = dimension_evidence.get("criteria", {})
    if not isinstance(criteria_results, Mapping):
        raise ValueError(f"dimension {dimension_id} criterion results must be an object")
    unknown = sorted(set(criteria_results) - set(criterion_ids))
    if unknown:
        raise ValueError(f"dimension {dimension_id} has unknown criteria: {unknown}")
    passed = count_boolean_criteria(criteria_results, criterion_ids, dimension_id)
    total = len(criterion_ids)
    raw_percent = 100.0 * passed / total
    evidence_class = str(dimension_evidence.get("evidence_class", raw_policy["evidence_class"]))
    point = _evidence_point(
        evidence_class,
        source_digest=str(dimension_evidence.get("source_tree_sha256", "")),
        release=str(dimension_evidence.get("release", "")),
        status=str(dimension_evidence.get("status", "UNKNOWN")),
    )
    return criterion_ids, passed, total, raw_percent, evidence_class, point

def _external_gaps(profile: Mapping[str, Any], evidence_dimensions: Mapping[str, Any]) -> list[str]:
    gaps: list[str] = []
    for criterion in profile.get("hard_external_predicates", ()):
        present = any(
            dimension.get("criteria", {}).get(str(criterion), False) is True
            for dimension in evidence_dimensions.values()
            if isinstance(dimension, Mapping)
        )
        if not present:
            gaps.append(str(criterion))
    return gaps


def evaluate_engineering_profile(
    profile: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    source_digest: str,
    release: str,
) -> dict[str, Any]:
    """Evaluate a preregistered readiness profile against explicit criterion results."""

    dimensions_payload = profile.get("dimensions")
    evidence_dimensions = evidence.get("dimensions")
    if not isinstance(dimensions_payload, Mapping) or not isinstance(evidence_dimensions, Mapping):
        raise ValueError("profile and evidence require dimension mappings")
    unknown_dimensions = sorted(set(evidence_dimensions) - set(dimensions_payload))
    if unknown_dimensions:
        raise ValueError(f"unknown evidence dimensions: {unknown_dimensions}")

    policies: list[DimensionPolicy] = []
    observations: dict[str, DimensionObservation] = {}
    details: dict[str, dict[str, Any]] = {}
    for dimension_id, raw_policy in dimensions_payload.items():
        if not isinstance(raw_policy, Mapping):
            raise ValueError(f"dimension {dimension_id} policy must be an object")
        raw_evidence = evidence_dimensions.get(dimension_id, {})
        if not isinstance(raw_evidence, Mapping):
            raise ValueError(f"dimension {dimension_id} evidence must be an object")
        _, passed, total, raw_percent, evidence_class, point = _criterion_summary(
            str(dimension_id), raw_policy, raw_evidence
        )
        policy = DimensionPolicy(str(dimension_id), float(raw_policy["weight"]))
        policies.append(policy)
        observations[str(dimension_id)] = DimensionObservation(raw_percent, point)
        details[str(dimension_id)] = {
            "passed": passed,
            "total": total,
            "raw_percent": round(raw_percent, 6),
            "evidence_class": evidence_class,
        }

    policy = ReadinessPolicy(tuple(policies), ())
    verdict = evaluate_readiness(policy, observations, {}, source_digest=source_digest, release=release)
    weight_by_id = {item.dimension_id: item.weight for item in policy.dimensions}
    for dimension_id, calibrated in verdict.dimension_scores.items():
        details[dimension_id]["calibrated_percent"] = calibrated
        details[dimension_id]["weighted_points"] = round(calibrated * weight_by_id[dimension_id], 6)

    target = readiness_target(profile.get("target_percent", 0.0))
    return {
        "schema": "korpus.engineering-readiness-result.v1",
        "profile_id": str(profile.get("profile_id", "")),
        "source_tree_sha256": source_digest,
        "release": release,
        "engineering_readiness_percent": verdict.engineering_readiness,
        "target_percent": target,
        "target_met": verdict.engineering_readiness >= target,
        "production_authorized_by_score": False,
        "dimensions": details,
        "external_or_tooling_gaps": _external_gaps(profile, evidence_dimensions),
    }
