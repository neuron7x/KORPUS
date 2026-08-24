"""Discrete and finite-domain contracts for adaptive runtime configuration."""

from __future__ import annotations

import math

from korpus.application.adaptive_types import (
    AdaptationPolicyLike,
    AdaptationStateLike,
    JudgedCandidateLike,
    ObservationWindowLike,
    RuntimeKnobsLike,
)
from korpus.application.numeric_contracts import (
    bounded_number,
    finite_number,
    finite_rate,
    strict_int,
)


def validate_runtime_knobs(v: RuntimeKnobsLike) -> None:
    if not all(strict_int(x) and x >= 1 for x in (v.candidate_budget, v.retrieval_timeout_ms)):
        raise ValueError("runtime budgets must be positive integers")
    if not all(
        finite_rate(x) for x in (v.minimum_score, v.minimum_query_coverage, v.minimum_support_score)
    ):
        raise ValueError("safety thresholds must be finite values in [0, 1]")


def _validate_policy_counts(v: AdaptationPolicyLike) -> None:
    counts = (
        v.min_candidate_budget,
        v.max_candidate_budget,
        v.candidate_step,
        v.min_timeout_ms,
        v.max_timeout_ms,
        v.timeout_step_ms,
        v.min_samples,
        v.healthy_windows_for_recall_expansion,
        v.cooldown_windows,
    )
    if not all(strict_int(x) for x in counts):
        raise ValueError("adaptation counts must be integers")
    if not 1 <= v.min_candidate_budget <= v.max_candidate_budget:
        raise ValueError("invalid candidate-budget bounds")
    if v.candidate_step < 1:
        raise ValueError("candidate_step must be a positive integer")
    if not 1 <= v.min_timeout_ms <= v.max_timeout_ms:
        raise ValueError("invalid timeout bounds")
    if v.timeout_step_ms < 1:
        raise ValueError("timeout_step_ms must be a positive integer")
    if v.min_samples < 1 or v.cooldown_windows < 0:
        raise ValueError("sample/cooldown bounds are invalid integers")
    if v.healthy_windows_for_recall_expansion < 1:
        raise ValueError("healthy window threshold must be a positive integer")


def _validate_policy_rates(v: AdaptationPolicyLike) -> None:
    if not finite_number(v.safety_step) or not 0 < v.safety_step <= 0.25:
        raise ValueError("safety_step must be finite and in (0, 0.25]")
    if not finite_number(v.max_safety_threshold) or not 0 < v.max_safety_threshold <= 1:
        raise ValueError("max_safety_threshold must be finite and in (0, 1]")
    values = (
        v.high_error_rate,
        v.high_contradiction_rate,
        v.high_overload_rate,
        v.low_recall,
        v.healthy_error_rate,
        v.healthy_overload_rate,
    )
    if not all(finite_rate(x) for x in values):
        raise ValueError("rate policy values must be finite and in [0, 1]")
    if v.healthy_error_rate > v.high_error_rate:
        raise ValueError("healthy_error_rate cannot exceed high_error_rate")
    if v.healthy_overload_rate > v.high_overload_rate:
        raise ValueError("healthy_overload_rate cannot exceed high_overload_rate")
    if (
        not all(finite_number(x) for x in (v.high_latency_ms, v.healthy_latency_ms))
        or not 0 <= v.healthy_latency_ms <= v.high_latency_ms
        or v.high_latency_ms <= 0
    ):
        raise ValueError("healthy latency must not exceed finite positive high latency")


def validate_adaptation_policy(v: AdaptationPolicyLike) -> None:
    _validate_policy_counts(v)
    _validate_policy_rates(v)


def validate_observation_window(v: ObservationWindowLike) -> None:
    if not all(strict_int(x) and x >= 0 for x in (v.sequence, v.samples)):
        raise ValueError("window sequence/sample count must be non-negative integers")
    if not finite_number(v.p95_latency_ms) or v.p95_latency_ms < 0:
        raise ValueError("latency must be finite and non-negative")
    if not all(
        finite_rate(x)
        for x in (v.error_rate, v.contradiction_rate, v.overload_rate, v.recall_at_20)
    ):
        raise ValueError("window rates must be finite values in [0, 1]")


def validate_adaptation_state(v: AdaptationStateLike) -> None:
    if (
        not strict_int(v.last_change_sequence)
        or not strict_int(v.consecutive_healthy_windows)
        or v.last_change_sequence < -1
        or v.consecutive_healthy_windows < 0
    ):
        raise ValueError("adaptation state counters must be integers in valid ranges")


def validate_judged_candidate(v: JudgedCandidateLike) -> None:
    if not strict_int(v.relevance) or not 0 <= v.relevance <= 3:
        raise ValueError("relevance must be an integer in [0, 3]")
    if not all(finite_rate(x) for x in (v.authority_score, v.semantic_score, v.temporal_score)):
        raise ValueError("component scores must be finite values in [0, 1]")


def validate_simplex_step(step: object) -> float:
    parsed = bounded_number(step, 0.0, 0.5)
    if (
        parsed is None
        or parsed == 0.0
        or not math.isclose(round(1 / parsed) * parsed, 1.0, abs_tol=1e-9)
    ):
        raise ValueError("step must be finite, positive, <= 0.5, and evenly divide 1")
    return parsed
