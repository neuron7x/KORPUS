from __future__ import annotations

import hashlib
import math
from datetime import date
from types import SimpleNamespace

import pytest
from korpus.application.contextual_projection import build_contextual_projection
from korpus.application.controller_profile import (
    ControllerLeaf,
    ControllerProfile,
    ControllerRule,
    FeatureRange,
    RuleCondition,
)
from korpus.application.evidence_state import build_evidence_state, feature_schema_sha256
from korpus.application.predictive_evidence_control import (
    PredictiveEvidenceController,
    RetrievalAction,
    _condition_matches,
    _support_failure,
)
from korpus.application.risk import QueryRisk
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


def _evidence(text: str, *, score: float = 0.8, coverage: float = 0.75) -> RetrievedEvidence:
    document = DocumentRecord(
        canonical_title="Статут зв'язку",
        corpus_id="public",
        issuer="МОУ",
        jurisdiction="UA",
        document_type="doctrine",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1.0",
        source_hash="a" * 64,
        object_key="docs/a",
        mime_type="text/plain",
        publication_date=date(2025, 1, 1),
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.APPROVED,
    )
    span = EvidenceSpanRecord(version_id=version.id, ordinal=0, section="Зв'язок", text=text)
    return RetrievedEvidence(
        span=span,
        document=document,
        version=version,
        score=score,
        query_coverage=coverage,
        lexical_score=2.0,
        character_score=0.4,
        authority_bonus=1.0,
        rank=1,
    )


def _profile(*, release: str = "b" * 64, admitted: bool = True) -> ControllerProfile:
    return ControllerProfile(
        profile_id="pec-test-v1",
        dataset_sha256="1" * 64,
        system_manifest_sha256="2" * 64,
        evaluation_protocol_sha256="3" * 64,
        replay_receipt_sha256="4" * 64,
        training_receipt_sha256="5" * 64,
        feature_schema_sha256=feature_schema_sha256(),
        corpus_release_id=release,
        answer_calibration_id="cal-v1",
        admission_status="PASS",
        controller_risk_limit=0.05,
        minimum_leaf_samples=30,
        rules=(
            ControllerRule(
                rule_id="sufficient",
                conditions=(
                    RuleCondition(
                        feature="original_query_has_eligible_evidence", operator="eq", value=True
                    ),
                    RuleCondition(feature="top1_score", operator="ge", value=0.5),
                ),
                leaf=ControllerLeaf(
                    leaf_id="stop",
                    action="STOP_USE_CURRENT_EVIDENCE",
                    admitted=admitted,
                    observed_samples=100,
                    upper_error_bound=0.01,
                    support={"top1_score": FeatureRange(minimum=0.5, maximum=1.0)},
                ),
            ),
            ControllerRule(
                rule_id="recover",
                conditions=(),
                leaf=ControllerLeaf(
                    leaf_id="plan",
                    action="PLAN_QUERY_VARIANTS",
                    admitted=True,
                    observed_samples=100,
                    upper_error_bound=0.01,
                ),
            ),
        ),
    )


def test_evidence_state_fingerprint_is_deterministic_and_query_sensitive() -> None:
    evidence = [_evidence("Кожен запис журналу містить дату та відповідальну особу.")]
    first = build_evidence_state(
        query="що містить запис журналу",
        risk=QueryRisk.STANDARD,
        evidence=evidence,
        eligible_evidence_count=1,
    )
    second = build_evidence_state(
        query="що містить запис журналу",
        risk=QueryRisk.STANDARD,
        evidence=list(evidence),
        eligible_evidence_count=1,
    )
    changed = build_evidence_state(
        query="інше питання",
        risk=QueryRisk.STANDARD,
        evidence=evidence,
        eligible_evidence_count=1,
    )
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != changed.fingerprint


def test_empty_and_single_candidate_state_edges_are_finite() -> None:
    empty = build_evidence_state(
        query="невідоме питання",
        risk=QueryRisk.STANDARD,
        evidence=[],
        eligible_evidence_count=0,
    )
    single = build_evidence_state(
        query="журнал дата",
        risk=QueryRisk.STANDARD,
        evidence=[_evidence("журнал дата")],
        eligible_evidence_count=1,
    )
    assert empty.top1_score == 0.0 and empty.score_concentration == 0.0
    assert single.top1_top2_margin == single.top1_score
    assert single.score_concentration == 1.0


def test_controller_is_deterministic_and_source_bound() -> None:
    state = build_evidence_state(
        query="журнал дата",
        risk=QueryRisk.STANDARD,
        evidence=[_evidence("журнал дата")],
        eligible_evidence_count=1,
    )
    controller = PredictiveEvidenceController(_profile(), shadow_mode=False)
    left = controller.decide(state, corpus_release_id="b" * 64, answer_calibration_id="cal-v1")
    right = controller.decide(state, corpus_release_id="b" * 64, answer_calibration_id="cal-v1")
    stale = controller.decide(state, corpus_release_id="c" * 64, answer_calibration_id="cal-v1")
    assert left == right
    assert left.effective_action is RetrievalAction.STOP_USE_CURRENT_EVIDENCE
    assert stale.effective_action is RetrievalAction.BASELINE
    assert stale.fallback_reason == "corpus_release_mismatch"


def test_unadmitted_leaf_and_out_of_support_fall_back() -> None:
    state = build_evidence_state(
        query="журнал дата",
        risk=QueryRisk.STANDARD,
        evidence=[_evidence("журнал дата", score=0.8)],
        eligible_evidence_count=1,
    )
    controller = PredictiveEvidenceController(_profile(admitted=False), shadow_mode=False)
    decision = controller.decide(state, corpus_release_id="b" * 64, answer_calibration_id="cal-v1")
    assert decision.effective_action is RetrievalAction.BASELINE
    assert decision.fallback_reason == "leaf_not_admitted"


def test_semantic_action_refuses_when_semantic_is_unavailable() -> None:
    profile = _profile().model_copy(
        update={
            "rules": (
                ControllerRule(
                    rule_id="semantic",
                    conditions=(),
                    leaf=ControllerLeaf(
                        leaf_id="semantic-leaf",
                        action="ENABLE_SEMANTIC_RETRIEVAL",
                        admitted=True,
                        observed_samples=100,
                        upper_error_bound=0.01,
                    ),
                ),
            )
        }
    )
    state = build_evidence_state(
        query="журнал",
        risk=QueryRisk.STANDARD,
        evidence=[],
        eligible_evidence_count=0,
        semantic_available=False,
    )
    decision = PredictiveEvidenceController(profile, shadow_mode=False).decide(
        state, corpus_release_id="b" * 64, answer_calibration_id="cal-v1"
    )
    assert decision.effective_action is RetrievalAction.BASELINE
    assert decision.fallback_reason == "semantic_retrieval_unavailable"


def test_shadow_mode_never_changes_runtime_action() -> None:
    state = build_evidence_state(
        query="журнал",
        risk=QueryRisk.STANDARD,
        evidence=[_evidence("журнал")],
        eligible_evidence_count=1,
    )
    decision = PredictiveEvidenceController(_profile(), shadow_mode=True).decide(
        state, corpus_release_id="b" * 64, answer_calibration_id="cal-v1"
    )
    assert decision.predicted_action is RetrievalAction.STOP_USE_CURRENT_EVIDENCE
    assert decision.effective_action is RetrievalAction.BASELINE
    assert decision.fallback_reason == "shadow_mode"


def test_contextual_projection_cannot_change_evidence_text_or_hash() -> None:
    item = _evidence("Оригінальний доказовий текст.")
    projection = build_contextual_projection(
        item.span, item.document, item.version, approved_aliases=["радіозв'язок"]
    )
    assert projection.retrieval_text != item.span.text
    assert projection.evidence_text == item.span.text
    assert projection.evidence_sha256 == item.span.text_hash
    assert hashlib.sha256(projection.evidence_text.encode()).hexdigest() == item.span.text_hash


def test_profile_rejects_wrong_feature_schema_and_underpowered_admitted_leaf() -> None:
    with pytest.raises(ValueError, match="feature schema digest"):
        _profile().model_copy(update={"feature_schema_sha256": "0" * 64}).model_validate(
            _profile().model_copy(update={"feature_schema_sha256": "0" * 64})
        )
    with pytest.raises(ValueError, match="minimum sample"):
        ControllerProfile(
            profile_id="pec-bad",
            dataset_sha256="1" * 64,
            system_manifest_sha256="2" * 64,
            evaluation_protocol_sha256="3" * 64,
            replay_receipt_sha256="4" * 64,
            training_receipt_sha256="5" * 64,
            feature_schema_sha256=feature_schema_sha256(),
            corpus_release_id="b" * 64,
            answer_calibration_id="cal-v1",
            admission_status="PASS",
            controller_risk_limit=0.05,
            minimum_leaf_samples=30,
            rules=(
                ControllerRule(
                    rule_id="bad",
                    leaf=ControllerLeaf(
                        leaf_id="bad",
                        action="ABSTAIN",
                        admitted=True,
                        observed_samples=2,
                        upper_error_bound=0.01,
                    ),
                ),
            ),
        )


# Чотири гілки цього модуля не виконував ЖОДЕН прогін (вимір покриття 04.09.2026).
# Три з них — відмови на нечислових та нескінченних значеннях, тобто саме те, що
# відрізняє «умова не справдилась» від «умову неможливо перевірити». Четверта —
# дорога підтримки листа: наявний `test_unadmitted_leaf_and_out_of_support_fall_back`
# називає її в заголовку, але стверджує лише `leaf_not_admitted`.


def test_matching_rule_still_falls_back_when_the_state_leaves_leaf_support() -> None:
    """Правило спрацювало — і цього НЕ досить.

    Умова правила й носій листа — різні твердження: перше каже «цей випадок мій»,
    друге — «на таких значеннях я вимірював». Стан може задовольнити перше й вийти
    за друге, і тоді дія листа не має доказової підстави.
    """
    profile = _profile().model_copy(
        update={
            "rules": (
                ControllerRule(
                    rule_id="matches-but-unsupported",
                    conditions=(RuleCondition(feature="top1_score", operator="ge", value=0.5),),
                    leaf=ControllerLeaf(
                        leaf_id="narrow",
                        action="STOP_USE_CURRENT_EVIDENCE",
                        admitted=True,
                        observed_samples=100,
                        upper_error_bound=0.01,
                        support={"top1_score": FeatureRange(minimum=0.99, maximum=1.0)},
                    ),
                ),
            )
        }
    )
    state = build_evidence_state(
        query="журнал дата",
        risk=QueryRisk.STANDARD,
        evidence=[_evidence("журнал дата", score=0.8)],
        eligible_evidence_count=1,
    )
    decision = PredictiveEvidenceController(profile, shadow_mode=False).decide(
        state, corpus_release_id="b" * 64, answer_calibration_id="cal-v1"
    )
    assert decision.effective_action is RetrievalAction.BASELINE
    assert decision.fallback_reason == "state_below_support:top1_score"
    assert decision.rule_id == "matches-but-unsupported"


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_ordered_comparison_refuses_a_non_finite_bound(value: float) -> None:
    """Нескінченність не порівнюють — її відхиляють.

    `nan >= x` хибне, `inf >= x` істинне для всього: обидва відповіді на питання,
    якого не ставили. Правильний вихід — «умова не перевірена», тобто False.
    """
    state = build_evidence_state(
        query="журнал",
        risk=QueryRisk.STANDARD,
        evidence=[_evidence("журнал", score=0.8)],
        eligible_evidence_count=1,
    )
    condition = SimpleNamespace(feature="top1_score", operator="ge", value=value)
    assert _condition_matches(state, condition) is False  # type: ignore[arg-type]


def test_an_unknown_operator_matches_nothing_instead_of_defaulting_to_true() -> None:
    """Невідомий оператор — не дозвіл.

    Схема оператор валідує, тож ця гілка захисна: вона існує на випадок, коли
    правило прийде повз схему. Вона мусить відмовляти, а не пропускати.
    """
    state = build_evidence_state(
        query="журнал",
        risk=QueryRisk.STANDARD,
        evidence=[_evidence("журнал", score=0.8)],
        eligible_evidence_count=1,
    )
    condition = SimpleNamespace(feature="top1_score", operator="within", value=0.5)
    assert _condition_matches(state, condition) is False  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (math.inf, "unsupported_non_finite_feature:top1_score"),
        (math.nan, "unsupported_non_finite_feature:top1_score"),
        ("0.8", "unsupported_non_numeric_feature:top1_score"),
        (True, "unsupported_non_numeric_feature:top1_score"),
    ],
)
def test_support_check_names_why_a_feature_could_not_be_judged(value: object, expected: str) -> None:
    """Причина відмови названа окремо для «не число» й «не скінченне».

    Обидва випадки означають «судити не можна», але походження в них різне, і звіт,
    який їх зливає, приховує, чи це вада ознаки, чи вада вимірювання.
    """
    state = SimpleNamespace(feature_value=lambda name: value)
    support = {"top1_score": FeatureRange(minimum=0.0, maximum=1.0)}
    assert _support_failure(state, support) == expected  # type: ignore[arg-type]
