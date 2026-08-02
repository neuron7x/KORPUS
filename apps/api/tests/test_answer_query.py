from uuid import uuid4

import pytest

from korpus.application.answer_query import AnswerPolicy, AnswerQuery
from korpus.domain.models import (
    AccessTier,
    AnswerStatus,
    AuthorityClass,
    Citation,
    EvidenceSpan,
    Query,
    ReviewState,
)
from korpus.infrastructure.in_memory import (
    EvidenceBoundStubGenerator,
    InMemoryAuditSink,
    InMemoryRetriever,
)


@pytest.mark.asyncio
async def test_abstains_without_approved_evidence() -> None:
    audit = InMemoryAuditSink()
    service = AnswerQuery(
        InMemoryRetriever(), EvidenceBoundStubGenerator(), audit, AnswerPolicy()
    )
    answer = await service.execute(Query(text="Який документ це визначає?"))
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert answer.citations == []
    assert audit.events[0][0] == "answer.completed"


@pytest.mark.asyncio
async def test_answers_with_approved_evidence_and_citation() -> None:
    citation = Citation(document_id=uuid4(), title="Test", page=7, quote="Verified fact.")
    span = EvidenceSpan(
        citation=citation,
        retrieval_score=0.91,
        access_tier=AccessTier.PUBLIC,
        review_state=ReviewState.APPROVED,
        authority=AuthorityClass.OFFICIAL_UA,
    )
    service = AnswerQuery(
        InMemoryRetriever([span]),
        EvidenceBoundStubGenerator(),
        InMemoryAuditSink(),
        AnswerPolicy(),
    )
    answer = await service.execute(Query(text="Що визначає джерело?"))
    assert answer.status is AnswerStatus.ANSWERED
    assert answer.citations == [citation]
    assert answer.confidence == 0.91

