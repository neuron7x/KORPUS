"""Deterministic, bounded adaptation for KORPUS runtime/calibration knobs.

"Plasticity" here deliberately does *not* mean online self-modifying code.  The
system observes a finite metrics window and produces a content-addressed proposal.
A proposal is pure, replayable and bounded by policy.  Safety thresholds may tighten
automatically but may never relax automatically; capacity/latency knobs may move only
inside declared bounds.  Promotion remains a separate governed action.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

from korpus.application.adaptive_contracts import (
    validate_adaptation_policy,
    validate_adaptation_state,
    validate_observation_window,
    validate_runtime_knobs,
)


class AdaptationAction(StrEnum):
    NOOP = "noop"
    TIGHTEN_SAFETY = "tighten_safety"
    REDUCE_WORK = "reduce_work"
    EXPAND_RECALL = "expand_recall"


@dataclass(frozen=True, slots=True)
class RuntimeKnobs:
    candidate_budget: int
    retrieval_timeout_ms: int
    minimum_score: float
    minimum_query_coverage: float
    minimum_support_score: float

    def __post_init__(self) -> None:
        validate_runtime_knobs(self)


@dataclass(frozen=True, slots=True)
class AdaptationPolicy:
    min_candidate_budget: int = 32
    max_candidate_budget: int = 1024
    candidate_step: int = 32
    min_timeout_ms: int = 300
    max_timeout_ms: int = 5000
    timeout_step_ms: int = 100
    safety_step: float = 0.02
    max_safety_threshold: float = 0.99
    min_samples: int = 200
    high_error_rate: float = 0.02
    high_contradiction_rate: float = 0.005
    high_overload_rate: float = 0.02
    high_latency_ms: float = 900.0
    low_recall: float = 0.90
    healthy_error_rate: float = 0.005
    healthy_overload_rate: float = 0.005
    healthy_latency_ms: float = 650.0
    healthy_windows_for_recall_expansion: int = 3
    cooldown_windows: int = 2

    def __post_init__(self) -> None:
        validate_adaptation_policy(self)


DEFAULT_ADAPTATION_POLICY = AdaptationPolicy()


@dataclass(frozen=True, slots=True)
class ObservationWindow:
    sequence: int
    samples: int
    p95_latency_ms: float
    error_rate: float
    contradiction_rate: float
    overload_rate: float
    recall_at_20: float

    def __post_init__(self) -> None:
        validate_observation_window(self)


@dataclass(frozen=True, slots=True)
class AdaptationState:
    knobs: RuntimeKnobs
    last_change_sequence: int = -1
    consecutive_healthy_windows: int = 0

    def __post_init__(self) -> None:
        validate_adaptation_state(self)


@dataclass(frozen=True, slots=True)
class AdaptationProposal:
    action: AdaptationAction
    input_state: AdaptationState
    observation: ObservationWindow
    proposed: RuntimeKnobs
    next_state: AdaptationState
    reasons: tuple[str, ...]
    policy_sha256: str
    proposal_sha256: str

    @property
    def previous(self) -> RuntimeKnobs:
        return self.input_state.knobs

    @property
    def window_sequence(self) -> int:
        return self.observation.sequence

    @property
    def changed(self) -> bool:
        return self.previous != self.proposed


def _clamp(value: int, lower: int, upper: int) -> int:
    return min(upper, max(lower, value))


def _tighten(value: float, policy: AdaptationPolicy) -> float:
    return min(policy.max_safety_threshold, round(value + policy.safety_step, 12))


def _healthy(window: ObservationWindow, policy: AdaptationPolicy) -> bool:
    return (
        window.error_rate <= policy.healthy_error_rate
        and window.contradiction_rate == 0.0
        and window.overload_rate <= policy.healthy_overload_rate
        and window.p95_latency_ms <= policy.healthy_latency_ms
    )


def _cooldown_elapsed(
    state: AdaptationState, window: ObservationWindow, policy: AdaptationPolicy
) -> bool:
    return (
        state.last_change_sequence < 0
        or window.sequence - state.last_change_sequence > policy.cooldown_windows
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _policy_digest(policy: AdaptationPolicy) -> str:
    return hashlib.sha256(_canonical_json(asdict(policy))).hexdigest()


def _canonical_payload(
    action: AdaptationAction,
    state: AdaptationState,
    observation: ObservationWindow,
    policy: AdaptationPolicy,
    proposed: RuntimeKnobs,
    next_state: AdaptationState,
    reasons: tuple[str, ...],
) -> bytes:
    payload = {
        "schema": "korpus.adaptation-proposal.v2",
        "action": action.value,
        "input_state": asdict(state),
        "observation": asdict(observation),
        "policy": asdict(policy),
        "proposed": asdict(proposed),
        "next_state": asdict(next_state),
        "reasons": list(reasons),
    }
    return _canonical_json(payload)


def propose_adaptation(
    state: AdaptationState,
    window: ObservationWindow,
    policy: AdaptationPolicy = DEFAULT_ADAPTATION_POLICY,
) -> AdaptationProposal:
    """Return one deterministic bounded proposal.

    Ordering is intentional and safety-critical:
    1. unsafe evidence tightens answer thresholds immediately, ignoring cooldown;
    2. overload reduces bounded work after cooldown;
    3. sustained healthy-but-low-recall operation may expand candidate work;
    4. otherwise no state mutation occurs.
    """

    reasons: tuple[str, ...]
    if window.samples < policy.min_samples:
        action = AdaptationAction.NOOP
        proposed = state.knobs
        reasons = ("insufficient_samples",)
        healthy_count = 0
    elif (
        window.error_rate > policy.high_error_rate
        or window.contradiction_rate > policy.high_contradiction_rate
    ):
        action = AdaptationAction.TIGHTEN_SAFETY
        proposed = RuntimeKnobs(
            candidate_budget=state.knobs.candidate_budget,
            retrieval_timeout_ms=state.knobs.retrieval_timeout_ms,
            minimum_score=_tighten(state.knobs.minimum_score, policy),
            minimum_query_coverage=_tighten(state.knobs.minimum_query_coverage, policy),
            minimum_support_score=_tighten(state.knobs.minimum_support_score, policy),
        )
        reasons = tuple(
            name
            for name, triggered in (
                ("error_rate", window.error_rate > policy.high_error_rate),
                (
                    "contradiction_rate",
                    window.contradiction_rate > policy.high_contradiction_rate,
                ),
            )
            if triggered
        )
        healthy_count = 0
    elif not _cooldown_elapsed(state, window, policy):
        action = AdaptationAction.NOOP
        proposed = state.knobs
        reasons = ("cooldown",)
        healthy_count = state.consecutive_healthy_windows + int(_healthy(window, policy))
    elif (
        window.overload_rate > policy.high_overload_rate
        or window.p95_latency_ms > policy.high_latency_ms
    ):
        action = AdaptationAction.REDUCE_WORK
        proposed = RuntimeKnobs(
            candidate_budget=_clamp(
                state.knobs.candidate_budget - policy.candidate_step,
                policy.min_candidate_budget,
                policy.max_candidate_budget,
            ),
            retrieval_timeout_ms=_clamp(
                state.knobs.retrieval_timeout_ms - policy.timeout_step_ms,
                policy.min_timeout_ms,
                policy.max_timeout_ms,
            ),
            minimum_score=state.knobs.minimum_score,
            minimum_query_coverage=state.knobs.minimum_query_coverage,
            minimum_support_score=state.knobs.minimum_support_score,
        )
        reasons = tuple(
            name
            for name, triggered in (
                ("overload_rate", window.overload_rate > policy.high_overload_rate),
                ("p95_latency", window.p95_latency_ms > policy.high_latency_ms),
            )
            if triggered
        )
        healthy_count = 0
    else:
        healthy_count = state.consecutive_healthy_windows + int(_healthy(window, policy))
        may_expand = (
            _healthy(window, policy)
            and healthy_count >= policy.healthy_windows_for_recall_expansion
            and window.recall_at_20 < policy.low_recall
        )
        if may_expand:
            action = AdaptationAction.EXPAND_RECALL
            proposed = RuntimeKnobs(
                candidate_budget=_clamp(
                    state.knobs.candidate_budget + policy.candidate_step,
                    policy.min_candidate_budget,
                    policy.max_candidate_budget,
                ),
                retrieval_timeout_ms=_clamp(
                    state.knobs.retrieval_timeout_ms + policy.timeout_step_ms,
                    policy.min_timeout_ms,
                    policy.max_timeout_ms,
                ),
                minimum_score=state.knobs.minimum_score,
                minimum_query_coverage=state.knobs.minimum_query_coverage,
                minimum_support_score=state.knobs.minimum_support_score,
            )
            reasons = ("sustained_healthy_low_recall",)
            healthy_count = 0
        else:
            action = AdaptationAction.NOOP
            proposed = state.knobs
            reasons = ("stable",)

    changed = proposed != state.knobs
    next_state = AdaptationState(
        knobs=proposed,
        last_change_sequence=window.sequence if changed else state.last_change_sequence,
        consecutive_healthy_windows=healthy_count,
    )
    digest = hashlib.sha256(
        _canonical_payload(action, state, window, policy, proposed, next_state, reasons)
    ).hexdigest()
    return AdaptationProposal(
        action=action,
        input_state=state,
        observation=window,
        proposed=proposed,
        next_state=next_state,
        reasons=reasons,
        policy_sha256=_policy_digest(policy),
        proposal_sha256=digest,
    )


def validate_proposal(
    proposal: AdaptationProposal,
    policy: AdaptationPolicy = DEFAULT_ADAPTATION_POLICY,
) -> None:
    """Fail closed if a proposal violates the adaptation safety envelope."""

    expected_policy = _policy_digest(policy)
    if proposal.policy_sha256 != expected_policy:
        raise ValueError("adaptation proposal policy digest mismatch")
    expected = hashlib.sha256(
        _canonical_payload(
            proposal.action,
            proposal.input_state,
            proposal.observation,
            policy,
            proposal.proposed,
            proposal.next_state,
            proposal.reasons,
        )
    ).hexdigest()
    if proposal.proposal_sha256 != expected:
        raise ValueError("adaptation proposal digest mismatch")
    knobs = proposal.proposed
    if not policy.min_candidate_budget <= knobs.candidate_budget <= policy.max_candidate_budget:
        raise ValueError("candidate budget escaped policy bounds")
    if not policy.min_timeout_ms <= knobs.retrieval_timeout_ms <= policy.max_timeout_ms:
        raise ValueError("retrieval timeout escaped policy bounds")
    # Automatic adaptation is one-way on safety.  Relaxation requires a separately
    # calibrated profile and governed promotion, not this controller.
    if knobs.minimum_score < proposal.previous.minimum_score:
        raise ValueError("automatic adaptation relaxed minimum_score")
    if knobs.minimum_query_coverage < proposal.previous.minimum_query_coverage:
        raise ValueError("automatic adaptation relaxed minimum_query_coverage")
    if knobs.minimum_support_score < proposal.previous.minimum_support_score:
        raise ValueError("automatic adaptation relaxed minimum_support_score")
