"""Formal, fail-closed algebra for engineering-readiness evidence.

The module deliberately separates two concepts that dashboards often collapse:

* *engineering maturity* is a weighted score over bounded dimensions; and
* *production authorization* is a conjunction of release-bound gate predicates.

A strong score can therefore never compensate for a failed mandatory gate.  Evidence
is modeled as a small partially ordered set.  Evidence from a different source tree
or release cannot be joined; callers must re-run or explicitly re-bind it instead of
silently mixing observations from different systems.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from math import isclose
from typing import Mapping, Sequence

from korpus.application.numeric_contracts import validate_evidence_flags

class EvidenceClass(IntEnum):
    """Increasing strength of evidence, not increasing certainty of a claim."""

    NONE = 0
    DECLARATIVE = 1
    STATIC = 2
    EXECUTED = 3
    EXECUTED_WITH_NEGATIVE_CONTROL = 4
    INDEPENDENT_ATTESTED = 5


@dataclass(frozen=True, slots=True)
class EvidencePoint:
    """One observation bound to the exact source/release it measured."""

    evidence_class: EvidenceClass
    source_digest: str
    release: str
    status: str
    executed: bool = False
    negative_control: bool = False
    independent: bool = False
    attested: bool = False

    def __post_init__(self) -> None:
        if self.source_digest and (
            len(self.source_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.source_digest)
        ):
            raise ValueError("source_digest must be an empty value or SHA-256 hex")
        if self.status not in {"PASS", "FAIL", "UNKNOWN"}:
            raise ValueError("status must be PASS, FAIL, or UNKNOWN")
        if self.evidence_class >= EvidenceClass.EXECUTED and not self.executed:
            raise ValueError("executed evidence class requires executed=True")
        if self.evidence_class >= EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL and not (
            self.executed and self.negative_control
        ):
            raise ValueError("negative-control evidence class requires execution and a control")
        validate_evidence_flags(int(self.evidence_class), int(EvidenceClass.INDEPENDENT_ATTESTED), independent=self.independent, attested=self.attested)
        if self.evidence_class >= EvidenceClass.INDEPENDENT_ATTESTED and not (
            self.executed and self.negative_control and self.independent and self.attested
        ):
            raise ValueError("independent attested evidence requires every lower-strength property")

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

@dataclass(frozen=True, slots=True)
class GateRequirement:
    gate_id: str
    minimum_class: EvidenceClass = EvidenceClass.EXECUTED
    require_negative_control: bool = False
    require_independent: bool = False
    require_attestation: bool = False

@dataclass(frozen=True, slots=True)
class DimensionPolicy:
    dimension_id: str
    weight: float
    ceiling_without_execution: float = 70.0
    ceiling_without_negative_control: float = 90.0
    ceiling_without_independent_attestation: float = 97.0

    def __post_init__(self) -> None:
        if not 0.0 < self.weight <= 1.0:
            raise ValueError("dimension weight must be in (0, 1]")
        ceilings = (
            self.ceiling_without_execution,
            self.ceiling_without_negative_control,
            self.ceiling_without_independent_attestation,
        )
        if any(not 0.0 <= value <= 100.0 for value in ceilings):
            raise ValueError("dimension ceilings must be percentages")
        if not ceilings[0] <= ceilings[1] <= ceilings[2]:
            raise ValueError("evidence ceilings must be monotone")


@dataclass(frozen=True, slots=True)
class DimensionObservation:
    score: float
    evidence: EvidencePoint

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 100.0:
            raise ValueError("dimension score must be in [0, 100]")


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    dimensions: tuple[DimensionPolicy, ...]
    mandatory_gates: tuple[GateRequirement, ...]

    def __post_init__(self) -> None:
        ids = [item.dimension_id for item in self.dimensions]
        if len(ids) != len(set(ids)):
            raise ValueError("dimension ids must be unique")
        gate_ids = [item.gate_id for item in self.mandatory_gates]
        if len(gate_ids) != len(set(gate_ids)):
            raise ValueError("gate ids must be unique")
        if not isclose(sum(item.weight for item in self.dimensions), 1.0, abs_tol=1e-12):
            raise ValueError("dimension weights must sum exactly to one within 1e-12")


@dataclass(frozen=True, slots=True)
class ReadinessVerdict:
    engineering_readiness: float
    production_authorized: bool
    dimension_scores: Mapping[str, float]
    gate_checks: Mapping[str, bool]
    blockers: tuple[str, ...]


def _same_identity(left: EvidencePoint, right: EvidencePoint) -> bool:
    return left.source_digest == right.source_digest and left.release == right.release

def dominates(left: EvidencePoint, right: EvidencePoint) -> bool:
    """Return whether ``left`` is at least as strong as ``right`` for one identity."""

    if not _same_identity(left, right):
        return False
    flags_left = (left.executed, left.negative_control, left.independent, left.attested)
    flags_right = (right.executed, right.negative_control, right.independent, right.attested)
    # UNKNOWN is bottom; contradictory PASS/FAIL outcomes are incomparable.
    outcome_dominates = right.status == "UNKNOWN" or left.status == right.status
    return (
        left.evidence_class >= right.evidence_class
        and all((not required) or present for present, required in zip(flags_left, flags_right))
        and outcome_dominates
    )

def join_evidence(left: EvidencePoint, right: EvidencePoint) -> EvidencePoint:
    """Join same-identity evidence; conflicting PASS/FAIL collapses fail-closed."""
    if not _same_identity(left, right):
        raise ValueError("cannot join evidence from different source/release identities")
    if left.status == right.status:
        status = left.status
    elif left.status == "UNKNOWN":
        status = right.status
    elif right.status == "UNKNOWN":
        status = left.status
    else:
        # Contradictory outcomes must not improve a release verdict.
        status = "FAIL"
    return EvidencePoint(
        evidence_class=max(left.evidence_class, right.evidence_class),
        source_digest=left.source_digest,
        release=left.release,
        status=status,
        executed=left.executed or right.executed,
        negative_control=left.negative_control or right.negative_control,
        independent=left.independent or right.independent,
        attested=left.attested or right.attested,
    )

def evidence_ceiling(policy: DimensionPolicy, evidence: EvidencePoint) -> float:
    if not evidence.executed:
        return policy.ceiling_without_execution
    if not evidence.negative_control:
        return policy.ceiling_without_negative_control
    if not (evidence.independent and evidence.attested):
        return policy.ceiling_without_independent_attestation
    return 100.0


def calibrated_dimension_score(
    policy: DimensionPolicy,
    observation: DimensionObservation,
    *,
    source_digest: str,
    release: str,
) -> float:
    """Apply identity and evidence-strength ceilings to one maturity observation."""

    evidence = observation.evidence
    if evidence.source_digest != source_digest or evidence.release != release:
        return 0.0
    if not evidence.passed:
        return 0.0
    return min(observation.score, evidence_ceiling(policy, evidence))


def evaluate_gate(
    requirement: GateRequirement,
    evidence: EvidencePoint | None,
    *,
    source_digest: str,
    release: str,
) -> tuple[bool, tuple[str, ...]]:
    prefix = requirement.gate_id
    if evidence is None:
        return False, (f"{prefix}.missing",)
    checks = {
        f"{prefix}.pass": evidence.passed,
        f"{prefix}.source_bound": evidence.source_digest == source_digest,
        f"{prefix}.release_bound": evidence.release == release,
        f"{prefix}.evidence_class": evidence.evidence_class >= requirement.minimum_class,
        f"{prefix}.negative_control": (
            not requirement.require_negative_control or evidence.negative_control
        ),
        f"{prefix}.independent": not requirement.require_independent or evidence.independent,
        f"{prefix}.attested": not requirement.require_attestation or evidence.attested,
    }
    failures = tuple(name for name, passed in checks.items() if not passed)
    return not failures, failures


def evaluate_readiness(
    policy: ReadinessPolicy,
    observations: Mapping[str, DimensionObservation],
    gates: Mapping[str, EvidencePoint],
    *,
    source_digest: str,
    release: str,
) -> ReadinessVerdict:
    """Evaluate maturity and authorization without allowing cross-compensation."""

    calibrated: dict[str, float] = {}
    missing_dimensions: list[str] = []
    total = 0.0
    for dimension in policy.dimensions:
        observation = observations.get(dimension.dimension_id)
        if observation is None:
            score = 0.0
            missing_dimensions.append(f"dimension.{dimension.dimension_id}.missing")
        else:
            score = calibrated_dimension_score(
                dimension,
                observation,
                source_digest=source_digest,
                release=release,
            )
        calibrated[dimension.dimension_id] = score
        total += dimension.weight * score

    gate_checks: dict[str, bool] = {}
    gate_failures: list[str] = []
    for requirement in policy.mandatory_gates:
        passed, failures = evaluate_gate(
            requirement,
            gates.get(requirement.gate_id),
            source_digest=source_digest,
            release=release,
        )
        gate_checks[requirement.gate_id] = passed
        gate_failures.extend(failures)

    blockers = tuple(missing_dimensions + gate_failures)
    return ReadinessVerdict(
        engineering_readiness=round(total, 6),
        production_authorized=not blockers,
        dimension_scores=calibrated,
        gate_checks=gate_checks,
        blockers=blockers,
    )


def maximum_single_dimension_effect(policy: ReadinessPolicy) -> Mapping[str, float]:
    """Maximum percentage-point change any one dimension can contribute."""

    return {item.dimension_id: round(item.weight * 100.0, 6) for item in policy.dimensions}


def critical_path_blockers(
    policy: ReadinessPolicy,
    gates: Mapping[str, EvidencePoint],
    *,
    source_digest: str,
    release: str,
) -> tuple[str, ...]:
    """Return mandatory gates that still block promotion, in policy order."""

    blocked: list[str] = []
    for requirement in policy.mandatory_gates:
        passed, _ = evaluate_gate(
            requirement,
            gates.get(requirement.gate_id),
            source_digest=source_digest,
            release=release,
        )
        if not passed:
            blocked.append(requirement.gate_id)
    return tuple(blocked)


def weighted_score_is_bounded(policy: ReadinessPolicy, scores: Sequence[float]) -> bool:
    """Small executable theorem used by tests and external model checkers."""

    if len(scores) != len(policy.dimensions):
        return False
    if any(not 0.0 <= score <= 100.0 for score in scores):
        return False
    value = sum(item.weight * score for item, score in zip(policy.dimensions, scores))
    return -1e-12 <= value <= 100.0 + 1e-12
