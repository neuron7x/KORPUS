"""Strict numeric/boolean predicates for operational release evidence."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from korpus.application.numeric_contracts import finite_number, finite_rate, nonnegative_count


def _rate_at_least(value: object, floor: object) -> bool:
    return finite_rate(value) and finite_rate(floor) and float(value) >= float(floor)


def _count_at_most(value: object, limit: object) -> bool:
    measured, ceiling = nonnegative_count(value), nonnegative_count(limit)
    return measured is not None and ceiling is not None and measured <= ceiling


def _count_at_least(value: object, limit: object) -> bool:
    measured, floor = nonnegative_count(value), nonnegative_count(limit)
    return measured is not None and floor is not None and measured >= floor


def _exact_bool(value: object, required: object) -> bool:
    return isinstance(value, bool) and isinstance(required, bool) and value is required


def _finite_nonnegative_at_most(value: object, limit: object) -> bool:
    if not finite_number(value) or not finite_number(limit):
        return False
    measured, ceiling = float(value), float(limit)
    return measured >= 0.0 and ceiling >= 0.0 and measured <= ceiling


def _survivors_ok(value: object, limit: object) -> bool:
    ceiling = nonnegative_count(limit)
    return isinstance(value, list) and ceiling is not None and len(value) <= ceiling


def _required_tables_ok(actual: object, required: object) -> bool:
    if not isinstance(actual, list) or not isinstance(required, list):
        return False
    if not all(isinstance(value, str) and value for value in (*actual, *required)):
        return False
    return set(required).issubset(set(actual))


def evaluate_operational_checks(
    evaluation: Mapping[str, Any], mutation: Mapping[str, Any],
    migration: Mapping[str, Any], scale: Mapping[str, Any],
    eval_policy: Mapping[str, Any], mutation_policy: Mapping[str, Any],
    migration_policy: Mapping[str, Any], scale_policy: Mapping[str, Any],
) -> dict[str, bool]:
    results = scale.get("results")
    results = results if isinstance(results, Mapping) else {}
    return {
        "eval_pass_rate": _rate_at_least(evaluation.get("pass_rate"), eval_policy.get("minimum_pass_rate")),
        "citation_integrity": _count_at_most(evaluation.get("citation_failures"), eval_policy.get("maximum_citation_failures")),
        "access_noninterference": _count_at_most(evaluation.get("leakage_failures"), eval_policy.get("maximum_leakage_failures")),
        "access_noninterference_measured": _count_at_least(evaluation.get("leakage_checks"), eval_policy.get("minimum_leakage_checks")),
        "determinism": _count_at_most(evaluation.get("determinism_failures"), eval_policy.get("maximum_determinism_failures")),
        "audit_chain": _exact_bool(evaluation.get("audit_valid"), eval_policy.get("require_audit_valid")),
        "critical_mutation_score": _rate_at_least(mutation.get("mutation_score"), mutation_policy.get("minimum_critical_mutation_score")),
        "critical_mutation_survivors": _survivors_ok(mutation.get("survived"), mutation_policy.get("maximum_survivors")),
        "migration_table_parity": _exact_bool(migration.get("table_set_match"), migration_policy.get("require_table_set_match")),
        "migration_required_tables": _required_tables_ok(migration.get("tables_actual"), migration_policy.get("required_tables")),
        "migration_audit_head": _exact_bool(migration.get("audit_head_seeded"), migration_policy.get("require_audit_head")),
        "migration_fts5": _exact_bool(migration.get("sqlite_fts5_present"), migration_policy.get("require_sqlite_fts5")),
        "scale_status": scale.get("status") == "PASS",
        "scale_metric_provenance": scale.get("metric_status") == scale_policy.get("metric_status"),
        "scale_top1": _rate_at_least(results.get("top1_recall"), scale_policy.get("minimum_top1_recall")),
        "scale_candidate_bound": _count_at_most(results.get("candidate_count"), scale_policy.get("maximum_candidate_count")),
        "scale_local_p95": _finite_nonnegative_at_most(results.get("query_latency_ms_p95"), scale_policy.get("maximum_local_p95_ms")),
    }
