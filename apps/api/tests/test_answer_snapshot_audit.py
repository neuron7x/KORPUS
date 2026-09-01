from __future__ import annotations

from datetime import date

from korpus.application.answer_audit import append_answer_audit
from korpus.application.corpus_snapshot import CorpusReadToken, authorization_scope_id
from korpus.application.risk import QueryRisk
from korpus.domain.models import AccessTier, Answer, AnswerStatus, Identity, QueryRequest


class _AuditRepository:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append_audit(self, identity, action, resource_type, resource_id, payload) -> None:
        self.events.append((action, payload))


def test_answer_audit_records_the_exact_snapshot_token_and_release() -> None:
    repository = _AuditRepository()
    identity = Identity(
        subject="snapshot-audit-user",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )
    corpora = frozenset({"public"})
    as_of = date(2026, 8, 14)
    token = CorpusReadToken(
        state_epoch=37,
        release_id="a" * 64,
        as_of=as_of,
        corpus_ids=corpora,
        authorization_scope_id=authorization_scope_id(identity, corpora),
    )
    query = QueryRequest(text="Що містить документ?", corpus_ids=["public"], as_of=as_of)
    answer = Answer(
        status=AnswerStatus.INSUFFICIENT_EVIDENCE,
        text="Контрольна fail-closed відповідь.",
        retrieval_score=0.0,
        evidence_coverage=0.0,
        query_coverage=0.0,
        decision_reason="audit_snapshot_control",
        calibration_id="audit-snapshot-control",
        corpus_release=token.release_id,
    )

    append_answer_audit(
        repository,  # type: ignore[arg-type]
        identity,
        query,
        answer,
        [],
        [],
        QueryRisk.STANDARD,
        minimum_score=0.1,
        minimum_query_coverage=0.1,
        minimum_support_score=0.1,
        token=token,
    )

    action, payload = repository.events[-1]
    assert action == "answer.completed"
    assert payload["corpus_release"] == token.release_id
    assert payload["corpus_snapshot"] == {
        "state_epoch": token.state_epoch,
        "release_id": token.release_id,
        "as_of": token.as_of.isoformat(),
        "corpus_ids": ["public"],
        "authorization_scope_id": token.authorization_scope_id,
    }
