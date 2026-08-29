"""Constrained PEC oracle: decision value first, resource Pareto second."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from korpus.application.numeric_contracts import finite_number

from korpus.application.predictive_evidence_control import RetrievalAction


class Outcome(Protocol):
    query_id: str
    action: RetrievalAction

    def resources(self) -> tuple[float, ...]: ...
    def admissible(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class OracleDecision:
    query_id: str
    action: RetrievalAction
    status: str
    reason: str
    admissible_actions: tuple[str, ...]


def _resource_vector(outcome: Outcome) -> tuple[float, ...]:
    vector = tuple(outcome.resources())
    if not vector:
        raise ValueError("resource vector must be non-empty")
    if any(not finite_number(value) or float(value) < 0.0 for value in vector):
        raise ValueError("resource vector must contain finite non-negative numbers")
    return tuple(float(value) for value in vector)


def dominates(left: Outcome, right: Outcome) -> bool:
    lvec, rvec = _resource_vector(left), _resource_vector(right)
    if len(lvec) != len(rvec):
        raise ValueError("resource vectors must have equal dimensionality")
    return all(l <= r for l, r in zip(lvec, rvec, strict=True)) and any(
        l < r for l, r in zip(lvec, rvec, strict=True)
    )


def _decision(
    query_id: str, action: RetrievalAction, status: str, reason: str, rows: list[Outcome]
) -> OracleDecision:
    return OracleDecision(
        query_id,
        action,
        status,
        reason,
        tuple(sorted(row.action.value for row in rows if row.admissible())),
    )


def solve_oracle(outcomes: Iterable[Outcome]) -> OracleDecision:
    rows = tuple(outcomes)
    if not rows:
        raise ValueError("oracle requires at least one action outcome")
    if len({row.query_id for row in rows}) != 1:
        raise ValueError("oracle outcomes must belong to one query")
    query_id = rows[0].query_id
    vectors = [_resource_vector(row) for row in rows]
    if len({len(vector) for vector in vectors}) != 1:
        raise ValueError("oracle resource vectors must have equal dimensionality")
    baseline = next(
        (row for row in rows if row.action is RetrievalAction.STOP_USE_CURRENT_EVIDENCE), None
    )
    if baseline is None:
        return _decision(
            query_id,
            RetrievalAction.BASELINE,
            "UNKNOWN",
            "missing_original_query_stop_baseline",
            [],
        )
    admissible = [row for row in rows if row.admissible()]
    if baseline.admissible():
        return _decision(
            query_id,
            RetrievalAction.STOP_USE_CURRENT_EVIDENCE,
            "PASS",
            "baseline_decision_already_admissible",
            admissible,
        )
    if not admissible:
        return _decision(
            query_id, RetrievalAction.ABSTAIN, "PASS", "no_admissible_answer_action", []
        )
    nondominated = [
        row for row in admissible if not any(dominates(other, row) for other in admissible)
    ]
    if len(nondominated) == 1:
        return _decision(
            query_id, nondominated[0].action, "PASS", "unique_pareto_minimum", admissible
        )
    if len({row.resources() for row in nondominated}) == 1:
        order = {
            action: index
            for index, action in enumerate(
                (
                    RetrievalAction.STOP_USE_CURRENT_EVIDENCE,
                    RetrievalAction.PLAN_QUERY_VARIANTS,
                    RetrievalAction.ENABLE_SEMANTIC_RETRIEVAL,
                    RetrievalAction.PLAN_AND_SEMANTIC,
                    RetrievalAction.ABSTAIN,
                    RetrievalAction.BASELINE,
                )
            )
        }
        winner = min(nondominated, key=lambda row: (order[row.action], row.action.value))
        return _decision(
            query_id, winner.action, "PASS", "resource_equivalent_canonical_action", admissible
        )
    return _decision(
        query_id, RetrievalAction.BASELINE, "UNKNOWN", "incomparable_pareto_minima", admissible
    )
