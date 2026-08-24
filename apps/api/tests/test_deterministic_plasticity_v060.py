from __future__ import annotations

from dataclasses import replace
from itertools import product

import pytest
from korpus.application.plasticity import (
    AdaptationAction,
    AdaptationPolicy,
    AdaptationState,
    ObservationWindow,
    RuntimeKnobs,
    propose_adaptation,
    validate_proposal,
)

BASE = RuntimeKnobs(256, 1200, 0.55, 0.60, 0.65)
POLICY = AdaptationPolicy()


def window(**updates) -> ObservationWindow:
    values = dict(
        sequence=10,
        samples=500,
        p95_latency_ms=500.0,
        error_rate=0.001,
        contradiction_rate=0.0,
        overload_rate=0.001,
        recall_at_20=0.95,
    )
    values.update(updates)
    return ObservationWindow(**values)


def test_same_state_and_observation_are_byte_identical_decisions() -> None:
    state = AdaptationState(BASE)
    left = propose_adaptation(state, window())
    right = propose_adaptation(state, window())
    assert left == right
    assert left.proposal_sha256 == right.proposal_sha256
    validate_proposal(left)


def test_safety_has_priority_and_may_bypass_cooldown() -> None:
    state = AdaptationState(BASE, last_change_sequence=9, consecutive_healthy_windows=9)
    proposal = propose_adaptation(
        state,
        window(error_rate=0.03, contradiction_rate=0.02, overload_rate=0.9, p95_latency_ms=5000),
    )
    assert proposal.action is AdaptationAction.TIGHTEN_SAFETY
    assert proposal.reasons == ("error_rate", "contradiction_rate")
    assert proposal.proposed.minimum_score > BASE.minimum_score
    assert proposal.proposed.minimum_support_score > BASE.minimum_support_score
    assert proposal.proposed.candidate_budget == BASE.candidate_budget
    validate_proposal(proposal)


def test_insufficient_evidence_never_changes_runtime() -> None:
    proposal = propose_adaptation(AdaptationState(BASE), window(samples=199, error_rate=1.0))
    assert proposal.action is AdaptationAction.NOOP
    assert not proposal.changed
    assert proposal.reasons == ("insufficient_samples",)


def test_cooldown_blocks_performance_tuning_but_tracks_health() -> None:
    proposal = propose_adaptation(
        AdaptationState(BASE, last_change_sequence=9, consecutive_healthy_windows=1),
        window(sequence=10, overload_rate=0.5),
    )
    assert proposal.action is AdaptationAction.NOOP
    assert proposal.reasons == ("cooldown",)


def test_overload_reduces_work_without_relaxing_safety() -> None:
    proposal = propose_adaptation(
        AdaptationState(BASE, last_change_sequence=1),
        window(overload_rate=0.5, p95_latency_ms=1500),
    )
    assert proposal.action is AdaptationAction.REDUCE_WORK
    assert proposal.proposed.candidate_budget == 224
    assert proposal.proposed.retrieval_timeout_ms == 1100
    assert proposal.proposed.minimum_score == BASE.minimum_score
    validate_proposal(proposal)


def test_sustained_health_can_expand_recall_within_bounds() -> None:
    state = AdaptationState(BASE, last_change_sequence=1, consecutive_healthy_windows=2)
    proposal = propose_adaptation(state, window(recall_at_20=0.80))
    assert proposal.action is AdaptationAction.EXPAND_RECALL
    assert proposal.proposed.candidate_budget == 288
    assert proposal.proposed.retrieval_timeout_ms == 1300
    validate_proposal(proposal)


def test_one_healthy_window_does_not_chase_recall() -> None:
    proposal = propose_adaptation(AdaptationState(BASE), window(recall_at_20=0.1))
    assert proposal.action is AdaptationAction.NOOP
    assert proposal.reasons == ("stable",)
    assert proposal.next_state.consecutive_healthy_windows == 1


def test_bounds_saturate_instead_of_overshooting() -> None:
    low = RuntimeKnobs(32, 300, 0.55, 0.60, 0.65)
    reduced = propose_adaptation(AdaptationState(low), window(overload_rate=0.5))
    assert reduced.proposed.candidate_budget == 32
    assert reduced.proposed.retrieval_timeout_ms == 300
    high = RuntimeKnobs(1024, 5000, 0.55, 0.60, 0.65)
    expanded = propose_adaptation(
        AdaptationState(high, consecutive_healthy_windows=2), window(recall_at_20=0.1)
    )
    assert expanded.proposed.candidate_budget == 1024
    assert expanded.proposed.retrieval_timeout_ms == 5000


def test_safety_thresholds_saturate() -> None:
    near_ceiling = RuntimeKnobs(256, 1200, 0.98, 0.99, 0.985)
    proposal = propose_adaptation(AdaptationState(near_ceiling), window(error_rate=0.5))
    assert proposal.proposed.minimum_score == 0.99
    assert proposal.proposed.minimum_query_coverage == 0.99
    assert proposal.proposed.minimum_support_score == 0.99
    validate_proposal(proposal)


def test_proposal_digest_commits_observation_state_and_policy() -> None:
    state = AdaptationState(BASE)
    first = propose_adaptation(state, window(error_rate=0.03))
    changed_observation = propose_adaptation(state, window(error_rate=0.04))
    changed_state = propose_adaptation(
        AdaptationState(BASE, consecutive_healthy_windows=1), window(error_rate=0.03)
    )
    changed_policy = propose_adaptation(
        state, window(error_rate=0.03), replace(POLICY, safety_step=0.03)
    )
    assert (
        len(
            {
                first.proposal_sha256,
                changed_observation.proposal_sha256,
                changed_state.proposal_sha256,
                changed_policy.proposal_sha256,
            }
        )
        == 4
    )
    assert first.policy_sha256 != changed_policy.policy_sha256


def test_validator_rejects_digest_tampering_and_safety_relaxation() -> None:
    proposal = propose_adaptation(AdaptationState(BASE), window(error_rate=0.5))
    with pytest.raises(ValueError, match="digest mismatch"):
        validate_proposal(replace(proposal, proposal_sha256="0" * 64))
    with pytest.raises(ValueError, match="policy digest mismatch"):
        validate_proposal(replace(proposal, policy_sha256="0" * 64))

    relaxed = replace(BASE, minimum_score=BASE.minimum_score - 0.1)
    bad = replace(proposal, proposed=relaxed)
    # Recompute through a valid proposal shape is intentionally impossible from the
    # public API; corrupting the payload must fail at the digest boundary first.
    with pytest.raises(ValueError):
        validate_proposal(bad)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"candidate_budget": 0},
        {"retrieval_timeout_ms": 0},
        {"minimum_score": float("nan")},
        {"minimum_support_score": 1.1},
    ],
)
def test_runtime_knob_validation_is_fail_closed(kwargs) -> None:
    values = dict(
        candidate_budget=256,
        retrieval_timeout_ms=1200,
        minimum_score=0.55,
        minimum_query_coverage=0.60,
        minimum_support_score=0.65,
    )
    values.update(kwargs)
    with pytest.raises(ValueError):
        RuntimeKnobs(**values)


def test_observation_validation_refuses_nonfinite_or_out_of_domain_values() -> None:
    for key, value in (
        ("p95_latency_ms", -1),
        ("p95_latency_ms", float("inf")),
        ("error_rate", -0.1),
        ("recall_at_20", 1.1),
    ):
        with pytest.raises(ValueError):
            window(**{key: value})


def test_exhaustive_small_state_space_preserves_core_invariants() -> None:
    actions = set()
    for error, contradiction, overload, latency, recall, healthy_count in product(
        (0.0, 0.03),
        (0.0, 0.01),
        (0.0, 0.03),
        (500.0, 1200.0),
        (0.80, 0.95),
        (0, 2),
    ):
        state = AdaptationState(
            BASE, last_change_sequence=1, consecutive_healthy_windows=healthy_count
        )
        proposal = propose_adaptation(
            state,
            window(
                sequence=10,
                error_rate=error,
                contradiction_rate=contradiction,
                overload_rate=overload,
                p95_latency_ms=latency,
                recall_at_20=recall,
            ),
        )
        validate_proposal(proposal)
        actions.add(proposal.action)
        assert (
            POLICY.min_candidate_budget
            <= proposal.proposed.candidate_budget
            <= POLICY.max_candidate_budget
        )
        assert (
            POLICY.min_timeout_ms <= proposal.proposed.retrieval_timeout_ms <= POLICY.max_timeout_ms
        )
        assert proposal.proposed.minimum_score >= BASE.minimum_score
        assert proposal.proposed.minimum_query_coverage >= BASE.minimum_query_coverage
        assert proposal.proposed.minimum_support_score >= BASE.minimum_support_score
    assert actions == set(AdaptationAction)


def test_recall_expansion_requires_current_window_to_be_healthy() -> None:
    """Historical health cannot authorize expansion after the current window degrades."""
    state = AdaptationState(BASE, last_change_sequence=1, consecutive_healthy_windows=3)
    proposal = propose_adaptation(
        state,
        window(error_rate=0.01, recall_at_20=0.10),  # degraded vs healthy, below safety trip
    )
    assert proposal.action is AdaptationAction.NOOP
    assert proposal.proposed == BASE
    assert proposal.next_state.consecutive_healthy_windows == 3
    validate_proposal(proposal)
