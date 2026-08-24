from __future__ import annotations

import hashlib
import json

from korpus.application.plasticity import (
    AdaptationAction,
    AdaptationState,
    ObservationWindow,
    RuntimeKnobs,
    propose_adaptation,
    validate_proposal,
)


def _trace() -> tuple[str, AdaptationState, set[AdaptationAction]]:
    state = AdaptationState(RuntimeKnobs(256, 1200, 0.55, 0.60, 0.65))
    events = []
    actions = set()
    for sequence in range(1, 5001):
        # Fully deterministic periodic fault schedule: safety events dominate overload;
        # low-recall windows appear only in otherwise healthy periods.
        safety = sequence % 257 == 0
        overloaded = sequence % 61 in {0, 1, 2}
        low_recall = sequence % 43 in {0, 1, 2, 3}
        observation = ObservationWindow(
            sequence=sequence,
            samples=500,
            p95_latency_ms=1400.0 if overloaded else 500.0,
            error_rate=0.04 if safety else 0.001,
            contradiction_rate=0.01 if safety else 0.0,
            overload_rate=0.08 if overloaded else 0.001,
            recall_at_20=0.82 if low_recall else 0.96,
        )
        proposal = propose_adaptation(state, observation)
        validate_proposal(proposal)
        actions.add(proposal.action)
        state = proposal.next_state
        events.append((sequence, proposal.action.value, proposal.proposal_sha256))
        assert 32 <= state.knobs.candidate_budget <= 1024
        assert 300 <= state.knobs.retrieval_timeout_ms <= 5000
        assert state.knobs.minimum_score >= 0.55
        assert state.knobs.minimum_query_coverage >= 0.60
        assert state.knobs.minimum_support_score >= 0.65
    canonical = json.dumps(events, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest(), state, actions


def test_five_thousand_window_fault_schedule_is_replayable_and_bounded() -> None:
    first_digest, first_state, first_actions = _trace()
    second_digest, second_state, second_actions = _trace()
    assert first_digest == second_digest
    assert first_state == second_state
    assert first_actions == second_actions == set(AdaptationAction)
