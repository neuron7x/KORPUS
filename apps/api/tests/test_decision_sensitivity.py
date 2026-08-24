from __future__ import annotations

from datetime import date

import pytest

from korpus.application.decision_sensitivity import (
    additional_compute_has_decision_value,
    decision_transitions,
    estimate_decision_sensitivity,
)
from korpus.application.evidence_admission import admission_boundary_summary, eligible_evidence
from korpus.application.evidence_state import build_evidence_state
from korpus.application.pec_replay import ReplayOutcome
from korpus.application.predictive_evidence_control import RetrievalAction
from korpus.application.risk import QueryRisk, RiskThresholds
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    RetrievedEvidence,
    ReviewState,
)


def _evidence(
    *,
    score: float = 0.7,
    coverage: float = 0.7,
    authority: AuthorityClass = AuthorityClass.OFFICIAL_UA,
    review: ReviewState = ReviewState.APPROVED,
) -> RetrievedEvidence:
    document = DocumentRecord(
        canonical_title="Protocol",
        corpus_id="public",
        issuer="UA",
        jurisdiction="UA",
        document_type="doctrine",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1",
        source_hash="a" * 64,
        object_key="docs/a",
        mime_type="text/plain",
        publication_date=date(2026, 1, 1),
        authority=authority,
        review_state=review,
    )
    span = EvidenceSpanRecord(version_id=version.id, ordinal=0, section="S", text="alpha beta")
    return RetrievedEvidence(
        span=span,
        document=document,
        version=version,
        score=score,
        query_coverage=coverage,
        lexical_score=1.0,
        character_score=0.2,
        authority_bonus=1.0,
        rank=1,
    )


def _thresholds() -> RiskThresholds:
    return RiskThresholds(0.5, 0.6, 0.5, 0.74)


def _outcome(
    action: RetrievalAction,
    *,
    status: str,
    quality: bool,
    auth: bool = True,
    error: bool = False,
) -> ReplayOutcome:
    return ReplayOutcome(
        query_id="q",
        group_id="g",
        action=action,
        state_fingerprint="a" * 64,
        features={},
        authorization_ok=auth,
        answer_error=error,
        quality_ok=quality,
        answer_status=status,
        gold_hit=quality,
        latency_ms=1.0,
        search_count=1,
        planner_calls=int(action is RetrievalAction.PLAN_QUERY_VARIANTS),
        semantic_calls=0,
        candidate_count=1,
        external_tokens=0,
        provider_cost_microunits=0,
    )


def test_boundary_margin_is_signed_distance_to_actual_retrieval_gate() -> None:
    below = _evidence(score=0.49, coverage=0.8)
    summary = admission_boundary_summary([below], _thresholds())
    assert summary.structural_candidate_exists is True
    assert summary.retrieval_gate_passed is False
    assert summary.best_score_margin == pytest.approx(-0.01)
    assert summary.minimum_admission_margin == pytest.approx(-0.01)
    assert summary.decision_boundary_distance == pytest.approx(0.01)
    assert eligible_evidence([below], _thresholds()) == []


def test_boundary_summary_and_runtime_eligibility_are_one_contract() -> None:
    evidence = [_evidence(score=0.51, coverage=0.61)]
    eligible = eligible_evidence(evidence, _thresholds())
    state = build_evidence_state(
        query="alpha beta",
        risk=QueryRisk.STANDARD,
        evidence=evidence,
        eligible_evidence_count=len(eligible),
        admission_thresholds=_thresholds(),
    )
    assert state.retrieval_gate_passed is True
    assert state.minimum_admission_margin == pytest.approx(0.01)
    assert state.decision_boundary_distance == pytest.approx(0.01)


def test_boundary_state_fails_closed_if_gate_and_feature_logic_diverge() -> None:
    evidence = [_evidence(score=0.49, coverage=0.8)]
    with pytest.raises(ValueError, match="disagrees with answer eligibility"):
        build_evidence_state(
            query="alpha beta",
            risk=QueryRisk.STANDARD,
            evidence=evidence,
            eligible_evidence_count=1,
            admission_thresholds=_thresholds(),
        )


def test_nonnormative_candidate_is_a_structural_block_not_fake_near_boundary() -> None:
    item = _evidence(score=1.0, coverage=1.0, authority=AuthorityClass.ADVERSARY)
    summary = admission_boundary_summary([item], _thresholds())
    assert summary.structural_candidate_exists is False
    assert summary.retrieval_gate_passed is False
    assert summary.minimum_admission_margin == -1.0


def test_decision_transition_distinguishes_prediction_change_from_decision_value() -> None:
    stop = _outcome(
        RetrievalAction.STOP_USE_CURRENT_EVIDENCE,
        status="insufficient_evidence",
        quality=False,
    )
    plan = _outcome(RetrievalAction.PLAN_QUERY_VARIANTS, status="answered", quality=True)
    transition = decision_transitions([stop, plan])[0]
    assert transition.decision_changed is True
    assert transition.quality_recovered is True
    assert additional_compute_has_decision_value(transition) is True


def test_same_external_decision_has_no_decision_value_when_baseline_is_already_good() -> None:
    stop = _outcome(RetrievalAction.STOP_USE_CURRENT_EVIDENCE, status="answered", quality=True)
    plan = _outcome(RetrievalAction.PLAN_QUERY_VARIANTS, status="answered", quality=True)
    transition = decision_transitions([stop, plan])[0]
    assert transition.decision_changed is False
    assert additional_compute_has_decision_value(transition) is False


def test_empirical_decision_sensitivity_reports_finite_sample_bounds() -> None:
    transitions = []
    for index in range(20):
        stop = _outcome(
            RetrievalAction.STOP_USE_CURRENT_EVIDENCE,
            status="insufficient_evidence",
            quality=False,
        )
        plan = _outcome(
            RetrievalAction.PLAN_QUERY_VARIANTS,
            status="answered" if index < 8 else "insufficient_evidence",
            quality=index < 8,
        )
        transitions.append(decision_transitions([stop, plan])[0])
    estimate = estimate_decision_sensitivity(
        transitions,
        action=RetrievalAction.PLAN_QUERY_VARIANTS,
        delta=0.05,
    )
    assert estimate.samples == 20
    assert estimate.flips == 8
    assert estimate.flip_rate == pytest.approx(0.4)
    assert 0.0 <= estimate.lower_bound <= estimate.flip_rate <= estimate.upper_bound <= 1.0
