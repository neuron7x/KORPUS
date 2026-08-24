"""Bounded inference control for assurance/reasoning loops.

The controller is deliberately epistemic rather than token-model specific. A cycle
may continue only while it changes the decision or adds evidence that was not already
observed. The loop stops at a fixpoint or at a hard budget. This prevents recursive
self-review from manufacturing confidence by repetition.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


from korpus.application.numeric_contracts import strict_int as _strict_int

class StopReason(StrEnum):
    CONTINUE = "CONTINUE"
    FIXPOINT = "FIXPOINT_NO_DECISION_OR_EVIDENCE_DELTA"
    MAX_CYCLES = "MAX_CYCLES"
    MAX_EVIDENCE_ITEMS = "MAX_EVIDENCE_ITEMS"
    MAX_CONFLICTS = "MAX_CONFLICTS"


@dataclass(frozen=True, slots=True)
class InferenceBudget:
    max_cycles: int
    max_evidence_items: int
    max_conflicts: int

    def __post_init__(self) -> None:
        if not _strict_int(self.max_cycles) or self.max_cycles <= 0:
            raise ValueError("max_cycles must be a positive integer")
        if not _strict_int(self.max_evidence_items) or self.max_evidence_items <= 0:
            raise ValueError("max_evidence_items must be a positive integer")
        if not _strict_int(self.max_conflicts) or self.max_conflicts < 0:
            raise ValueError("max_conflicts must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class InferenceCycle:
    cycle: int
    decision_fingerprint: str
    evidence_fingerprints: frozenset[str]
    conflict_fingerprints: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not _strict_int(self.cycle) or self.cycle <= 0:
            raise ValueError("cycle must be a positive integer")
        if not self.decision_fingerprint:
            raise ValueError("decision_fingerprint is required")
        if any(not item for item in self.evidence_fingerprints | self.conflict_fingerprints):
            raise ValueError("fingerprints must be non-empty")
@dataclass(frozen=True, slots=True)
class BudgetDecision:
    continue_inference: bool
    reason: StopReason
    cycles_used: int
    evidence_items: int
    conflicts: int
    decision_changed: bool
    new_evidence_added: bool


def decide_next(history: Iterable[InferenceCycle], budget: InferenceBudget) -> BudgetDecision:
    cycles = tuple(history)
    if not cycles:
        return BudgetDecision(True, StopReason.CONTINUE, 0, 0, 0, True, True)

    latest = cycles[-1]
    evidence_union = frozenset().union(*(item.evidence_fingerprints for item in cycles))
    conflict_union = frozenset().union(*(item.conflict_fingerprints for item in cycles))
    decision_changed = len(cycles) == 1 or latest.decision_fingerprint != cycles[-2].decision_fingerprint
    prior_evidence = (
        frozenset().union(*(item.evidence_fingerprints for item in cycles[:-1]))
        if len(cycles) > 1
        else frozenset()
    )
    new_evidence_added = bool(latest.evidence_fingerprints - prior_evidence)

    if len(cycles) >= budget.max_cycles:
        reason = StopReason.MAX_CYCLES
    elif len(evidence_union) >= budget.max_evidence_items:
        reason = StopReason.MAX_EVIDENCE_ITEMS
    elif len(conflict_union) > budget.max_conflicts:
        reason = StopReason.MAX_CONFLICTS
    elif len(cycles) > 1 and not decision_changed and not new_evidence_added:
        reason = StopReason.FIXPOINT
    else:
        reason = StopReason.CONTINUE

    return BudgetDecision(
        continue_inference=reason is StopReason.CONTINUE,
        reason=reason,
        cycles_used=len(cycles),
        evidence_items=len(evidence_union),
        conflicts=len(conflict_union),
        decision_changed=decision_changed,
        new_evidence_added=new_evidence_added,
    )
