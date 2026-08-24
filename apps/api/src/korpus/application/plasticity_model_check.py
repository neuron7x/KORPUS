"""Finite-state executable reference model for bounded runtime adaptation."""

from __future__ import annotations

from itertools import product

from korpus.application.plasticity import (
    AdaptationAction,
    AdaptationPolicy,
    AdaptationState,
    ObservationWindow,
    RuntimeKnobs,
    propose_adaptation,
    validate_proposal,
)


def check_grid(policy: AdaptationPolicy) -> dict[str, object]:
    base = RuntimeKnobs(256, 1200, 0.55, 0.60, 0.65)
    failures: list[str] = []
    transitions = 0
    action_counts = {action.value: 0 for action in AdaptationAction}
    digests: set[str] = set()
    grid = product(
        (0, 199, 200, 1000),
        (0.0, 0.005, 0.021, 0.5),
        (0.0, 0.006),
        (0.0, 0.005, 0.021, 0.5),
        (500.0, 901.0, 5000.0),
        (0.50, 0.899, 0.95),
        (0, 2, 4),
        (-1, 9),
    )
    for (
        samples,
        error,
        contradiction,
        overload,
        latency,
        recall,
        healthy_count,
        last_change,
    ) in grid:
        state = AdaptationState(
            base, last_change_sequence=last_change, consecutive_healthy_windows=healthy_count
        )
        window = ObservationWindow(10, samples, latency, error, contradiction, overload, recall)
        left = propose_adaptation(state, window, policy)
        right = propose_adaptation(state, window, policy)
        transitions += 1
        action_counts[left.action.value] += 1
        digests.add(left.proposal_sha256)
        checks = [
            (left == right, "same input produced a different proposal"),
            (left.proposed.minimum_score >= base.minimum_score, "minimum_score relaxed"),
            (
                left.proposed.minimum_query_coverage >= base.minimum_query_coverage,
                "minimum_query_coverage relaxed",
            ),
            (
                left.proposed.minimum_support_score >= base.minimum_support_score,
                "minimum_support_score relaxed",
            ),
            (
                policy.min_candidate_budget
                <= left.proposed.candidate_budget
                <= policy.max_candidate_budget,
                "candidate budget escaped bounds",
            ),
            (
                policy.min_timeout_ms
                <= left.proposed.retrieval_timeout_ms
                <= policy.max_timeout_ms,
                "timeout escaped bounds",
            ),
        ]
        unsafe = error > policy.high_error_rate or contradiction > policy.high_contradiction_rate
        checks.append(
            (
                samples < policy.min_samples
                or not unsafe
                or left.action is AdaptationAction.TIGHTEN_SAFETY,
                "unsafe observation did not receive safety priority",
            )
        )
        try:
            validate_proposal(left, policy)
        except ValueError as exc:
            failures.append(f"proposal failed validation: {exc}")
            break
        failed = next((message for passed, message in checks if not passed), None)
        if failed:
            failures.append(failed)
            break
    return {
        "states_checked": transitions,
        "unique_proposals": len(digests),
        "action_counts": action_counts,
        "invariants": {
            "pure_replay": not failures,
            "safety_thresholds_monotone": not failures,
            "resource_knobs_bounded": not failures,
            "unsafe_observations_have_priority": not failures,
        },
        "failures": failures,
    }
