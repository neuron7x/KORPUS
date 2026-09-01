from __future__ import annotations

import json
from datetime import date

from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.controller_profile import (
    ControllerLeaf,
    ControllerProfile,
    ControllerRule,
    RuleCondition,
)
from korpus.application.evidence_state import feature_schema_sha256
from korpus.application.predictive_evidence_control import PredictiveEvidenceController
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.domain.models import QueryRequest
from korpus.infrastructure.repository import audits
from sqlalchemy import select

from apps.api.tests.helpers import approve, ingest_text


class CountingPlanner:
    def __init__(self, suggestions: list[str] | None = None) -> None:
        self.calls = 0
        self.suggestions = suggestions or []

    def variants(self, question: str, subjects: list[str]) -> list[str]:
        self.calls += 1
        return list(self.suggestions)


class CountingRetriever:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.searches: list[str] = []

    def search(self, identity, text, corpus_ids, as_of, limit=8):
        self.searches.append(text)
        return self.delegate.search(identity, text, corpus_ids, as_of, limit)


def _controller(release_id: str, *, mode: str = "stop") -> PredictiveEvidenceController:
    if mode == "stop":
        rules = (
            ControllerRule(
                rule_id="sufficient",
                conditions=(
                    RuleCondition(
                        feature="original_query_has_eligible_evidence", operator="eq", value=True
                    ),
                ),
                leaf=ControllerLeaf(
                    leaf_id="stop",
                    action="STOP_USE_CURRENT_EVIDENCE",
                    admitted=True,
                    observed_samples=100,
                    upper_error_bound=0.01,
                ),
            ),
            ControllerRule(
                rule_id="recover",
                leaf=ControllerLeaf(
                    leaf_id="plan",
                    action="PLAN_QUERY_VARIANTS",
                    admitted=True,
                    observed_samples=100,
                    upper_error_bound=0.01,
                ),
            ),
        )
    elif mode == "abstain":
        rules = (
            ControllerRule(
                rule_id="abstain",
                leaf=ControllerLeaf(
                    leaf_id="abstain",
                    action="ABSTAIN",
                    admitted=True,
                    observed_samples=100,
                    upper_error_bound=0.01,
                ),
            ),
        )
    else:
        rules = (
            ControllerRule(
                rule_id="plan",
                leaf=ControllerLeaf(
                    leaf_id="plan",
                    action="PLAN_QUERY_VARIANTS",
                    admitted=True,
                    observed_samples=100,
                    upper_error_bound=0.01,
                ),
            ),
        )
    profile = ControllerProfile(
        profile_id="pec-integration-v1",
        dataset_sha256="1" * 64,
        system_manifest_sha256="2" * 64,
        evaluation_protocol_sha256="3" * 64,
        replay_receipt_sha256="4" * 64,
        training_receipt_sha256="5" * 64,
        feature_schema_sha256=feature_schema_sha256(),
        corpus_release_id=release_id,
        answer_calibration_id="pec-test-cal",
        admission_status="PASS",
        controller_risk_limit=0.05,
        minimum_leaf_samples=30,
        rules=rules,
    )
    return PredictiveEvidenceController(profile, shadow_mode=False)


def _service(client, admin_identity, planner: CountingPlanner, release_id: str):
    return ExtractiveAnswerService(
        client.app.state.repository,
        HybridLexicalRetriever(client.app.state.repository),
        client.app.state.policy,
        AnswerPolicy(0.1, 0.1, 0.1, "pec-test-cal"),
        query_planner=planner,
        predictive_controller=_controller(release_id),
    )


def test_easy_query_stops_after_original_retrieval_and_does_not_call_planner(
    client, admin_identity
) -> None:
    result = ingest_text(client)
    approve(client, result["version"]["id"])
    query = QueryRequest(text="Що має містити кожен запис?", as_of=date(2026, 8, 21))
    release_id = client.app.state.corpus_snapshot_reader.capture(
        admin_identity, frozenset({"public"}), query.as_of
    ).release_id
    planner = CountingPlanner(["дата відповідальна особа"])
    answer = _service(client, admin_identity, planner, release_id).execute(admin_identity, query)
    assert answer.status.value == "answered"
    assert planner.calls == 0


def test_stale_profile_falls_back_to_baseline_and_calls_planner(client, admin_identity) -> None:
    result = ingest_text(client)
    approve(client, result["version"]["id"])
    query = QueryRequest(text="Що має містити кожен запис?", as_of=date(2026, 8, 21))
    planner = CountingPlanner(["дата відповідальна особа"])
    service = ExtractiveAnswerService(
        client.app.state.repository,
        HybridLexicalRetriever(client.app.state.repository),
        client.app.state.policy,
        AnswerPolicy(0.1, 0.1, 0.1, "pec-test-cal"),
        query_planner=planner,
        predictive_controller=_controller("f" * 64),
    )
    answer = service.execute(admin_identity, query)
    assert answer.status.value == "answered"
    assert planner.calls == 1


def test_controller_cannot_turn_insufficient_evidence_into_an_answer(
    client, admin_identity
) -> None:
    query = QueryRequest(text="Який пароль адміністратора системи?", as_of=date(2026, 8, 21))
    release_id = client.app.state.corpus_snapshot_reader.capture(
        admin_identity, frozenset({"public"}), query.as_of
    ).release_id
    planner = CountingPlanner([])
    answer = _service(client, admin_identity, planner, release_id).execute(admin_identity, query)
    assert answer.status.value == "insufficient_evidence"
    assert answer.citations == []


def test_controller_trace_reaches_completed_answer_audit(client, admin_identity) -> None:
    result = ingest_text(client)
    approve(client, result["version"]["id"])
    query = QueryRequest(text="Що має містити кожен запис?", as_of=date(2026, 8, 21))
    release_id = client.app.state.corpus_snapshot_reader.capture(
        admin_identity, frozenset({"public"}), query.as_of
    ).release_id
    planner = CountingPlanner(["дата відповідальна особа"])
    _service(client, admin_identity, planner, release_id).execute(admin_identity, query)
    with client.app.state.repository.engine.begin() as connection:
        payload_raw = connection.execute(
            select(audits.c.payload_json)
            .where(audits.c.action == "answer.completed")
            .order_by(audits.c.sequence.desc())
            .limit(1)
        ).scalar_one()
    payload = json.loads(payload_raw)
    assert payload["pec"]["profile_id"] == "pec-integration-v1"
    assert payload["pec"]["state_fingerprint"]
    assert payload["pec"]["predicted_action"] == "STOP_USE_CURRENT_EVIDENCE"
    assert payload["pec"]["effective_action"] == "STOP_USE_CURRENT_EVIDENCE"
    assert payload["pec"]["retrieval_gate_passed"] is True
    assert payload["pec"]["decision_boundary_distance"] >= 0.0
    assert isinstance(payload["pec"]["minimum_admission_margin"], float)


def test_removing_controller_restores_baseline_answer_semantics_without_data_migration(
    client, admin_identity
) -> None:
    result = ingest_text(client)
    approve(client, result["version"]["id"])
    query = QueryRequest(text="Що має містити кожен запис?", as_of=date(2026, 8, 21))
    baseline_planner = CountingPlanner(["дата відповідальна особа"])
    baseline_service = ExtractiveAnswerService(
        client.app.state.repository,
        HybridLexicalRetriever(client.app.state.repository),
        client.app.state.policy,
        AnswerPolicy(0.1, 0.1, 0.1, "pec-test-cal"),
        query_planner=baseline_planner,
    )
    baseline = baseline_service.execute(admin_identity, query)
    stale_planner = CountingPlanner(["дата відповідальна особа"])
    stale_service = ExtractiveAnswerService(
        client.app.state.repository,
        HybridLexicalRetriever(client.app.state.repository),
        client.app.state.policy,
        AnswerPolicy(0.1, 0.1, 0.1, "pec-test-cal"),
        query_planner=stale_planner,
        predictive_controller=_controller("f" * 64),
    )
    restored = stale_service.execute(admin_identity, query)
    assert restored.model_dump(exclude={"id", "created_at"}) == baseline.model_dump(
        exclude={"id", "created_at"}
    )
    assert baseline_planner.calls == 1
    assert stale_planner.calls == 1


def test_controller_abstain_is_terminal_even_when_first_pass_has_eligible_evidence(
    client, admin_identity
) -> None:
    result = ingest_text(client)
    approve(client, result["version"]["id"])
    query = QueryRequest(text="Що має містити кожен запис?", as_of=date(2026, 8, 21))
    release_id = client.app.state.corpus_snapshot_reader.capture(
        admin_identity, frozenset({"public"}), query.as_of
    ).release_id
    planner = CountingPlanner(["дата відповідальна особа"])
    service = ExtractiveAnswerService(
        client.app.state.repository,
        HybridLexicalRetriever(client.app.state.repository),
        client.app.state.policy,
        AnswerPolicy(0.1, 0.1, 0.1, "pec-test-cal"),
        query_planner=planner,
        predictive_controller=_controller(release_id, mode="abstain"),
    )
    answer = service.execute(admin_identity, query)
    assert answer.status.value == "insufficient_evidence"
    assert answer.decision_reason == "pec_controller_abstain"
    assert answer.citations == []
    assert planner.calls == 0


def test_planner_escalation_does_not_repeat_original_lexical_search(client, admin_identity) -> None:
    result = ingest_text(client)
    approve(client, result["version"]["id"])
    query = QueryRequest(text="Що має містити кожен запис?", as_of=date(2026, 8, 21))
    release_id = client.app.state.corpus_snapshot_reader.capture(
        admin_identity, frozenset({"public"}), query.as_of
    ).release_id
    planner = CountingPlanner(["дата відповідальна особа"])
    retriever = CountingRetriever(HybridLexicalRetriever(client.app.state.repository))
    service = ExtractiveAnswerService(
        client.app.state.repository,
        retriever,
        client.app.state.policy,
        AnswerPolicy(0.1, 0.1, 0.1, "pec-test-cal"),
        query_planner=planner,
        predictive_controller=_controller(release_id, mode="plan"),
    )
    answer = service.execute(admin_identity, query)
    assert answer.status.value == "answered"
    assert retriever.searches == [query.text, "дата відповідальна особа"]
