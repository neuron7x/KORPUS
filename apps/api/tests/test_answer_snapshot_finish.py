from __future__ import annotations

from apps.api.tests.helpers import ingest_text
from korpus.application.answer_snapshot import SnapshotAnswerRuntime, SnapshotAuditPolicy
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.application.risk import QueryRisk
from korpus.domain.models import QueryRequest


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
