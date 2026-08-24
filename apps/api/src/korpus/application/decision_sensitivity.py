"""Decision-sensitivity primitives for PEC-v2 / Decision-Gradient Computing.

The online runtime never fabricates counterfactual worlds.  It exposes cheap signed
margins to the *actual* retrieval-admission boundary.  Counterfactual action flips are
measured offline from replay outcomes, where they can be falsified and source-bound.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from korpus.application.pec_replay import ReplayOutcome
from korpus.application.predictive_evidence_control import RetrievalAction
from korpus.application.statistical_bounds import hoeffding_two_sided_interval


@dataclass(frozen=True, slots=True)
class DecisionTransition:
    query_id: str
    baseline_action: RetrievalAction
    candidate_action: RetrievalAction
    baseline_decision: str
    candidate_decision: str
    decision_changed: bool
    candidate_admissible: bool
    baseline_admissible: bool
    safety_recovered: bool
    quality_recovered: bool


@dataclass(frozen=True, slots=True)
class DecisionSensitivityEstimate:
    action: RetrievalAction
    samples: int
    flips: int
    flip_rate: float
    lower_bound: float
    upper_bound: float


def external_decision(row: ReplayOutcome) -> str:
    """Decision visible outside the retrieval controller, not an internal score."""
    return row.answer_status


def transition_from_baseline(
    baseline: ReplayOutcome,
    candidate: ReplayOutcome,
) -> DecisionTransition:
    if baseline.query_id != candidate.query_id:
        raise ValueError("decision transition rows must belong to the same query")
    return DecisionTransition(
        query_id=baseline.query_id,
        baseline_action=baseline.action,
        candidate_action=candidate.action,
        baseline_decision=external_decision(baseline),
        candidate_decision=external_decision(candidate),
        decision_changed=external_decision(baseline) != external_decision(candidate),
        candidate_admissible=candidate.admissible(),
        baseline_admissible=baseline.admissible(),
        safety_recovered=(not baseline.authorization_ok or baseline.answer_error)
        and candidate.authorization_ok
        and not candidate.answer_error,
        quality_recovered=(not baseline.quality_ok) and candidate.quality_ok,
    )


def decision_transitions(
    outcomes: Iterable[ReplayOutcome],
    *,
    baseline_action: RetrievalAction = RetrievalAction.STOP_USE_CURRENT_EVIDENCE,
) -> tuple[DecisionTransition, ...]:
    rows = tuple(outcomes)
    baseline = next((row for row in rows if row.action is baseline_action), None)
    if baseline is None:
        raise ValueError(f"missing decision baseline action: {baseline_action.value}")
    return tuple(
        transition_from_baseline(baseline, row)
        for row in rows
        if row.action is not baseline_action
    )


def estimate_decision_sensitivity(
    transitions: Iterable[DecisionTransition],
    *,
    action: RetrievalAction,
    delta: float = 0.05,
) -> DecisionSensitivityEstimate:
    selected = [row for row in transitions if row.candidate_action is action]
    samples = len(selected)
    flips = sum(row.decision_changed for row in selected)
    rate = flips / samples if samples else 0.0
    lower, upper = hoeffding_two_sided_interval(flips, samples, delta)
    return DecisionSensitivityEstimate(
        action=action,
        samples=samples,
        flips=flips,
        flip_rate=rate,
        lower_bound=lower,
        upper_bound=upper,
    )


def additional_compute_has_decision_value(transition: DecisionTransition) -> bool:
    """Necessary causal condition for spending extra compute in replay.

    A non-baseline action has decision value only when it recovers safety/quality or
    changes the external decision while remaining admissible.  Merely producing a
    different ranking or a faster noisy latency sample is not decision value.
    """
    if not transition.candidate_admissible:
        return False
    return transition.safety_recovered or transition.quality_recovered or transition.decision_changed
