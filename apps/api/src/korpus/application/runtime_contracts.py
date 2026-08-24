"""Finite/discrete constructor contracts for runtime control loops."""
from __future__ import annotations
from korpus.application.numeric_contracts import finite_number, strict_int


def admission_parameters(capacity: object, timeout: object, per_subject: object) -> tuple[int, float, int | None]:
    if not strict_int(capacity) or capacity < 1:
        raise ValueError("invalid admission capacity: must be a positive integer")
    if not finite_number(timeout) or timeout < 0:
        raise ValueError("wait_timeout_seconds must be finite and non-negative")
    if per_subject is not None and (not strict_int(per_subject) or not 1 <= per_subject <= capacity):
        raise ValueError("per_subject_limit must be an integer in [1, capacity]")
    return capacity, float(timeout), per_subject


def circuit_parameters(threshold: object, timeout: object) -> tuple[int, float]:
    if not strict_int(threshold) or threshold < 1:
        raise ValueError("invalid circuit breaker failure_threshold: must be a positive integer")
    if not finite_number(timeout) or timeout <= 0:
        raise ValueError("invalid circuit breaker recovery_timeout_seconds: must be finite and positive")
    return threshold, float(timeout)

def validate_retrieval_limits(candidate_budget: object, timeout_ms: object) -> None:
    if not strict_int(candidate_budget) or candidate_budget < 8:
        raise ValueError("candidate_budget must be an integer of at least 8")
    if not strict_int(timeout_ms) or timeout_ms < 10:
        raise ValueError("timeout_ms must be an integer of at least 10")

