from __future__ import annotations

from apps.api.tests.helpers import ingest_text
from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.answer_snapshot import SnapshotAnswerRuntime, SnapshotAuditPolicy
from korpus.application.corpus_snapshot import CorpusConsistencyError
from korpus.application.policy import PolicyEngine
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.application.risk import QueryRisk
from korpus.domain.models import AnswerStatus, QueryRequest


class _FailingSnapshotReader:
    def capture(self, identity, corpus_ids, as_of):
        raise CorpusConsistencyError("deterministic capture failure")

    def validate(self, identity, corpus_ids, as_of, token) -> None:
        raise AssertionError("validate must not run when capture failed")


def test_capture_failure_returns_audited_fail_closed_answer(
    client, admin_identity, monkeypatch
) -> None:
    repository = client.app.state.repository
    reader = _FailingSnapshotReader()
    monkeypatch.setattr(repository, "corpus_snapshot_reader", reader)
    service = ExtractiveAnswerService(
        repository,
        HybridLexicalRetriever(repository, candidate_budget=8),
        PolicyEngine(),
        AnswerPolicy(0.1, 0.1, 0.1, "capture-failure-control"),
        snapshot_reader=reader,
    )

    answer = service.execute(
        admin_identity,
        QueryRequest(text="Що має містити запис?", corpus_ids=["public"]),
    )

    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert answer.decision_reason == "corpus_snapshot_unavailable"
    assert answer.corpus_release == "snapshot-unavailable"


def test_answer_finish_rejects_a_release_stamp_not_owned_by_the_session(
    client, admin_identity
) -> None:
    repository = client.app.state.repository
    reader = client.app.state.corpus_snapshot_reader
    runtime = SnapshotAnswerRuntime(
        repository,
        HybridLexicalRetriever(repository, candidate_budget=8),
        SnapshotAuditPolicy(0.1, 0.1, 0.1, "release-ownership-control"),
        reader,
    )
    query = QueryRequest(text="Що має містити запис?")
    session = runtime.begin(admin_identity, query, frozenset({"public"}))
    foreign = runtime.abstain(
        "foreign-release",
        "foreign_release_control",
        "Контрольна відповідь з чужою міткою релізу.",
    )

    answer = session.finish(foreign, [], [], QueryRisk.STANDARD)
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert answer.decision_reason == "corpus_release_mismatch"
    assert answer.corpus_release == session.release_id


def test_answer_finish_revalidates_after_all_retrieval_work(client, admin_identity) -> None:
    repository = client.app.state.repository
    reader = client.app.state.corpus_snapshot_reader
    runtime = SnapshotAnswerRuntime(
        repository,
        HybridLexicalRetriever(repository, candidate_budget=8),
        SnapshotAuditPolicy(0.1, 0.1, 0.1, "final-validation-control"),
        reader,
    )
    query = QueryRequest(text="Що має містити запис?")
    session = runtime.begin(admin_identity, query, frozenset({"public"}))
    candidate = runtime.abstain(
        session.release_id,
        "pre_final_validation_control",
        "Контрольна відповідь до фінальної перевірки стану.",
    )

    # This mutation happens after token capture and before the answer linearization point.
    ingest_text(client, title="Late snapshot mutation", text="Новий стан корпусу.")

    answer = session.finish(candidate, [], [], QueryRisk.STANDARD)
    assert answer.decision_reason == "corpus_snapshot_changed"
    assert answer.corpus_release == session.release_id
