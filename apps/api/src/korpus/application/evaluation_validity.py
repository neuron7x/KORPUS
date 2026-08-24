"""Statistical and epistemic validity primitives for military-system TEVV.

This module deliberately separates *test execution* from *claim admissibility*.
A campaign can execute successfully and still be inadmissible evidence when its
system identity, corpus, evaluator independence, operational environment or
coverage contract is incomplete.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from korpus.application.numeric_contracts import finite_number
from korpus.application.statistical_bounds import wilson_score_interval


class HardFailureClass(StrEnum):
    ACCESS_LEAKAGE = "access_leakage"
    STALE_AUTHORITY = "stale_authority"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CITATION_INTEGRITY = "citation_integrity"
    MISSED_MANDATORY_ABSTENTION = "missed_mandatory_abstention"
    SOURCE_IDENTITY_MISMATCH = "source_identity_mismatch"
    OFFLINE_ROLLBACK_ACCEPTANCE = "offline_rollback_acceptance"


class TEVVDimension(StrEnum):
    MODEL_RETRIEVAL = "model_and_retrieval"
    HUMAN_SYSTEMS = "human_systems_integration"
    SYSTEMS_INTEGRATION = "systems_integration"
    OPERATIONAL_SUITABILITY = "operational_suitability"


class TestedSystemIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_tree_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    release: str = Field(min_length=1, max_length=128)
    harness_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    environment_identity: str = Field(min_length=1, max_length=512)

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        wire = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(wire.encode("utf-8")).hexdigest()


class EvaluationObservation(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1, max_length=200)
    cohort: str = Field(min_length=1, max_length=128)
    dimensions: frozenset[TEVVDimension] = Field(min_length=1)
    passed: bool
    hard_failures: tuple[HardFailureClass, ...] = ()
    latency_ms: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def hard_failure_cannot_pass(self) -> EvaluationObservation:
        if self.hard_failures and self.passed:
            raise ValueError("an observation with a hard failure cannot be marked passed")
        return self


class AdmissionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    minimum_cases: int = Field(default=400, ge=1)
    minimum_cases_per_required_cohort: int = Field(default=30, ge=1)
    maximum_hard_failure_rate_upper_95: float = Field(default=0.01, ge=0, le=1)
    hard_failures_observed_allowed: int = Field(default=0, ge=0)
    required_dimensions: frozenset[TEVVDimension] = Field(default=frozenset(TEVVDimension))
    required_cohorts: frozenset[str] = Field(default_factory=frozenset)
    independent_evaluation_required: bool = True
    real_domain_required: bool = True
    operational_environment_required: bool = True


class CampaignContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    tested_system: TestedSystemIdentity
    independent_evaluation: bool
    real_domain: bool
    operational_environment: bool


def wilson_interval(
    successes: int, total: int, *, z: float = 1.959963984540054
) -> tuple[float, float]:
    """Two-sided Wilson score interval for a Bernoulli proportion."""
    return wilson_score_interval(successes, total, z=z)


def percentile(values: Iterable[float], q: float) -> float | None:
    if not finite_number(q) or not 0.0 <= float(q) <= 1.0:
        raise ValueError("q must be finite and in [0, 1]")
    raw = list(values)
    if any(not finite_number(v) for v in raw):
        raise ValueError("percentile values must be finite numbers")
    seq = sorted(float(v) for v in raw)
    if not seq:
        return None
    if len(seq) == 1:
        return seq[0]
    pos = q * (len(seq) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return seq[lo]
    return seq[lo] + (seq[hi] - seq[lo]) * (pos - lo)


def _campaign_checks(
    rows: tuple[EvaluationObservation, ...],
    *,
    context: CampaignContext,
    policy: AdmissionPolicy,
    hard_upper: float,
    total_hard: int,
    dimensions: set[TEVVDimension],
    cohort_checks: dict[str, bool],
) -> dict[str, bool]:
    ids = [row.id for row in rows]
    return {
        "observations_present": bool(rows),
        "observation_ids_unique": len(ids) == len(set(ids)),
        "minimum_cases": len(rows) >= policy.minimum_cases,
        "required_dimensions_covered": policy.required_dimensions.issubset(dimensions),
        "required_cohorts_covered": all(cohort_checks.values()),
        "hard_failure_count_within_limit": total_hard <= policy.hard_failures_observed_allowed,
        "hard_failure_upper_95_within_limit": hard_upper
        <= policy.maximum_hard_failure_rate_upper_95,
        "independent_evaluation": context.independent_evaluation
        or not policy.independent_evaluation_required,
        "real_domain": context.real_domain or not policy.real_domain_required,
        "operational_environment": context.operational_environment
        or not policy.operational_environment_required,
    }


def _campaign_metrics(
    rows: tuple[EvaluationObservation, ...],
    *,
    hard_counts: Counter[str],
    hard_upper: float,
    dimensions: set[TEVVDimension],
    cohort_counts: Counter[str],
) -> dict[str, object]:
    passed = sum(row.passed for row in rows)
    latencies = [row.latency_ms for row in rows]
    return {
        "observations": len(rows),
        "passed": passed,
        "pass_rate": (passed / len(rows)) if rows else None,
        "hard_failure_observations": sum(bool(row.hard_failures) for row in rows),
        "hard_failure_counts": dict(sorted(hard_counts.items())),
        "hard_failure_rate_upper_95": hard_upper,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "dimensions_covered": sorted(d.value for d in dimensions),
        "cohort_counts": dict(sorted(cohort_counts.items())),
    }


def evaluate_campaign(
    observations: Iterable[EvaluationObservation],
    *,
    context: CampaignContext,
    policy: AdmissionPolicy,
) -> dict[str, object]:
    """Evaluate evidence admissibility; every admission predicate is conjunctive."""
    rows = tuple(observations)
    hard_counts: Counter[str] = Counter(
        failure.value for row in rows for failure in row.hard_failures
    )
    hard_observations = sum(bool(row.hard_failures) for row in rows)
    _, hard_upper = wilson_interval(hard_observations, len(rows))
    dimensions = {dimension for row in rows for dimension in row.dimensions}
    cohort_counts: Counter[str] = Counter(row.cohort for row in rows)
    cohort_checks = {
        cohort: cohort_counts[cohort] >= policy.minimum_cases_per_required_cohort
        for cohort in sorted(policy.required_cohorts)
    }
    checks = _campaign_checks(
        rows,
        context=context,
        policy=policy,
        hard_upper=hard_upper,
        total_hard=sum(hard_counts.values()),
        dimensions=dimensions,
        cohort_checks=cohort_checks,
    )
    return {
        "schema": "korpus.military-tevv-admission.v2",
        "tested_system_fingerprint": context.tested_system.fingerprint,
        "admitted": all(checks.values()),
        "checks": checks,
        "cohort_checks": cohort_checks,
        "metrics": _campaign_metrics(
            rows,
            hard_counts=hard_counts,
            hard_upper=hard_upper,
            dimensions=dimensions,
            cohort_counts=cohort_counts,
        ),
    }
