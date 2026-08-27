from __future__ import annotations

import pytest
from korpus.application.inference_budget import (
    InferenceBudget,
    InferenceCycle,
    StopReason,
    decide_next,
)

BUDGET = InferenceBudget(max_cycles=4, max_evidence_items=5, max_conflicts=1)


def cycle(
    number: int, decision: str, evidence: set[str], conflicts: set[str] | None = None
) -> InferenceCycle:
    return InferenceCycle(number, decision, frozenset(evidence), frozenset(conflicts or set()))


def test_empty_history_can_start() -> None:
    result = decide_next([], BUDGET)
    assert result.continue_inference
    assert result.reason is StopReason.CONTINUE


def test_new_evidence_allows_stable_decision_to_continue() -> None:
    result = decide_next([cycle(1, "A", {"e1"}), cycle(2, "A", {"e1", "e2"})], BUDGET)
    assert result.continue_inference
    assert result.new_evidence_added
    assert not result.decision_changed


def test_fixpoint_stops_recursive_review() -> None:
    result = decide_next([cycle(1, "A", {"e1"}), cycle(2, "A", {"e1"})], BUDGET)
    assert not result.continue_inference
    assert result.reason is StopReason.FIXPOINT


def test_decision_change_without_new_evidence_can_continue_once() -> None:
    result = decide_next([cycle(1, "A", {"e1"}), cycle(2, "B", {"e1"})], BUDGET)
    assert result.continue_inference
    assert result.decision_changed
    assert not result.new_evidence_added


def test_cycle_budget_is_hard_stop() -> None:
    history = [cycle(i, f"D{i}", {f"e{i}"}) for i in range(1, 5)]
    result = decide_next(history, BUDGET)
    assert result.reason is StopReason.MAX_CYCLES
    assert not result.continue_inference


def test_evidence_budget_is_hard_stop() -> None:
    result = decide_next([cycle(1, "A", {"e1", "e2", "e3", "e4", "e5"})], BUDGET)
    assert result.reason is StopReason.MAX_EVIDENCE_ITEMS


def test_conflict_budget_is_hard_stop() -> None:
    result = decide_next([cycle(1, "A", {"e1"}, {"c1", "c2"})], BUDGET)
    assert result.reason is StopReason.MAX_CONFLICTS


def test_invalid_budget_is_rejected() -> None:
    with pytest.raises(ValueError):
        InferenceBudget(max_cycles=0, max_evidence_items=1, max_conflicts=0)
