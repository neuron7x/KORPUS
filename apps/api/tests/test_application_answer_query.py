"""The behaviour matrix of the answer pipeline.

Each test fixes one branch of the product promise: refuse, abstain, hold for review,
or answer with citations. A green suite here means those four are distinguishable.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from conftest import CORPUS, NOW, make_principal, make_span
from korpus.application.answer_query import AnswerPolicy, AnswerQuery
from korpus.domain.models import (
    AccessTier,
    AnswerStatus,
    AuthorityClass,
    Claim,
    EvidenceSpan,
    Query,
    ReviewState,
)
from korpus.infrastructure.in_memory import (
    EvidenceBoundStubGenerator,
    FixedClock,
    InMemoryAuditSink,
    InMemoryRetriever,
)


class UncitedGenerator:
    async def compose(self, query: Query, evidence: list[EvidenceSpan]) -> list[Claim]:
        del query, evidence
        return [Claim(text="Твердження без джерела.", citation_indexes=())]


class OutOfRangeGenerator:
    async def compose(self, query: Query, evidence: list[EvidenceSpan]) -> list[Claim]:
        del query
        return [Claim(text="Посилання в нікуди.", citation_indexes=(len(evidence) + 5,))]


class EmptyGenerator:
    async def compose(self, query: Query, evidence: list[EvidenceSpan]) -> list[Claim]:
        del query, evidence
        return []


class FailingGenerator:
    async def compose(self, query: Query, evidence: list[EvidenceSpan]) -> list[Claim]:
        del query, evidence
        raise RuntimeError("provider unavailable")


class LeakingRetriever:
    """Models a defective adapter that ignores the tier argument entirely."""

    def __init__(self, spans: list[EvidenceSpan]) -> None:
        self._spans = spans

    async def search(
        self,
        query: Query,
        allowed_tiers: frozenset[AccessTier],
        allowed_corpora: frozenset[UUID],
        limit: int = 8,
    ) -> list[EvidenceSpan]:
        del query, allowed_tiers, allowed_corpora, limit
        return list(self._spans)


class RecordingRetriever(InMemoryRetriever):
    def __init__(self, spans: list[EvidenceSpan] | None = None) -> None:
        super().__init__(spans)
        self.seen_tiers: frozenset[AccessTier] | None = None
        self.seen_corpora: frozenset[UUID] | None = None
        self.seen_limit = 0
        self.calls = 0

    async def search(
        self,
        query: Query,
        allowed_tiers: frozenset[AccessTier],
        allowed_corpora: frozenset[UUID],
        limit: int = 8,
    ) -> list[EvidenceSpan]:
        self.seen_tiers = allowed_tiers
        self.seen_corpora = allowed_corpora
        self.seen_limit = limit
        self.calls += 1
        return await super().search(query, allowed_tiers, allowed_corpora, limit)


def build(
    spans: list[EvidenceSpan] | None = None,
    *,
    generator: object | None = None,
    retriever: object | None = None,
    policy: AnswerPolicy | None = None,
    audit: InMemoryAuditSink | None = None,
) -> tuple[AnswerQuery, InMemoryAuditSink]:
    sink = audit or InMemoryAuditSink()
    service = AnswerQuery(
        retriever=retriever or InMemoryRetriever(spans or []),  # type: ignore[arg-type]
        generator=generator or EvidenceBoundStubGenerator(),  # type: ignore[arg-type]
        audit=sink,
        policy=policy or AnswerPolicy(),
        clock=FixedClock(NOW),
    )
    return service, sink


async def test_answers_when_evidence_is_approved_and_scored() -> None:
    service, _ = build([make_span(score=0.91)])
    answer = await service.execute(Query(text="Що визначає джерело?"), make_principal())
    assert answer.status is AnswerStatus.ANSWERED
    assert len(answer.citations) == 1
    assert answer.confidence == 0.91
    assert answer.citation_coverage == 1.0


async def test_every_claim_of_an_answered_response_carries_a_citation() -> None:
    service, _ = build([make_span(), make_span()])
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.claims
    assert all(claim.citation_indexes for claim in answer.claims)
    assert all(
        index in range(len(answer.citations))
        for claim in answer.claims
        for index in claim.citation_indexes
    )


async def test_abstains_when_nothing_is_retrieved() -> None:
    service, _ = build([])
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert answer.citations == []


async def test_abstains_when_evidence_is_retrieved_but_not_approved() -> None:
    """The promise itself: found, but not approved, is still a refusal."""
    for state in (
        ReviewState.QUARANTINED,
        ReviewState.METADATA_REVIEWED,
        ReviewState.CONTENT_REVIEWED,
        ReviewState.REJECTED,
    ):
        service, _ = build([make_span(review=state, score=0.99)])
        answer = await service.execute(Query(text="питання"), make_principal())
        assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE, state
        assert answer.citations == []


async def test_abstains_when_evidence_is_below_the_score_threshold() -> None:
    service, _ = build([make_span(score=0.71)], policy=AnswerPolicy(minimum_score=0.72))
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE


async def test_threshold_boundary_is_inclusive() -> None:
    service, _ = build([make_span(score=0.72)], policy=AnswerPolicy(minimum_score=0.72))
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.ANSWERED


async def test_abstains_when_the_only_source_is_superseded() -> None:
    service, _ = build([make_span(superseded_by=uuid4())])
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE


async def test_abstains_when_the_only_source_has_expired() -> None:
    service, _ = build([make_span(valid_until=NOW - timedelta(days=1))])
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE


async def test_abstains_when_the_only_source_is_adversary_material() -> None:
    service, _ = build([make_span(authority=AuthorityClass.ADVERSARY)])
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE


async def test_denies_a_corpus_the_principal_does_not_hold() -> None:
    service, sink = build([make_span()])
    answer = await service.execute(
        Query(text="питання", corpus_ids=[uuid4()]), make_principal()
    )
    assert answer.status is AnswerStatus.ACCESS_DENIED
    assert answer.citations == []
    assert sink.events[0][1]["denial_reason"] == "corpus_not_authorized"


async def test_omitting_corpus_ids_does_not_widen_the_search(  ) -> None:
    """Naming no corpus means "my grant", not "everything".

    The first cut enforced authorization only against callers polite enough to declare
    what they were reaching for: omit the optional field and every corpus at your tier
    was searched. This is that hole, kept open by a test.
    """
    foreign = make_span(text="порядок евакуації", corpus_id=uuid4())
    service, _ = build([foreign])
    answer = await service.execute(Query(text="порядок евакуації"), make_principal())
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert answer.citations == []


async def test_a_principal_without_a_grant_reads_nothing() -> None:
    service, _ = build([make_span()])
    answer = await service.execute(
        Query(text="питання"), make_principal(corpora=frozenset())
    )
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE


async def test_retriever_is_told_which_corpora_it_may_search() -> None:
    retriever = RecordingRetriever([])
    service, _ = build(retriever=retriever)
    await service.execute(Query(text="питання"), make_principal())
    assert retriever.seen_corpora == frozenset({CORPUS})


async def test_evidence_outside_the_grant_is_dropped_even_if_the_index_returns_it() -> None:
    foreign = make_span(corpus_id=uuid4())
    service, sink = build(retriever=LeakingRetriever([foreign]))
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.REQUIRES_HUMAN_REVIEW
    assert answer.citations == []
    assert any(event == "evidence.tier_violation" for event, _ in sink.events)


async def test_candidates_are_fetched_wider_than_the_answer() -> None:
    """Eligibility is decided here, so the candidate set must not be cut by the index.

    Eight unapproved chunks match the query better than the one approved source. When
    the retriever was asked for exactly `maximum_spans`, the governing document never
    reached the filter and the system abstained while holding the answer.
    """
    question = "порядок евакуації поранених негайно"
    # Each decoy matches all four query terms (score 1.0); the approved source matches
    # three of four (0.75) — above the 0.72 floor, but ranked ninth.
    decoys = [
        make_span(text=question, review=ReviewState.QUARANTINED) for _ in range(8)
    ]
    official = make_span(text="порядок евакуації поранених")
    from korpus.infrastructure.lexical import LexicalRetriever

    service, _ = build(retriever=LexicalRetriever([*decoys, official]),
                       policy=AnswerPolicy(maximum_spans=8))
    answer = await service.execute(Query(text=question), make_principal())
    assert answer.status is AnswerStatus.ANSWERED
    assert answer.citations[0].chunk_id == official.chunk_id


async def test_one_uncited_claim_in_twenty_blocks_the_answer() -> None:
    """Coverage 0.95 clears the floor; the promise still fails, so the answer is held."""

    class NineteenOfTwenty:
        async def compose(
            self, query: Query, evidence: list[EvidenceSpan]
        ) -> list[Claim]:
            del query, evidence
            cited = [Claim(text=f"твердження {i}", citation_indexes=(0,)) for i in range(19)]
            return [*cited, Claim(text="БЕЗ ДЖЕРЕЛА")]

    service, _ = build([make_span()], generator=NineteenOfTwenty())
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.citation_coverage == pytest.approx(0.95)
    assert answer.status is AnswerStatus.REQUIRES_HUMAN_REVIEW
    assert "БЕЗ ДЖЕРЕЛА" not in answer.text


async def test_denial_happens_before_retrieval() -> None:
    retriever = RecordingRetriever([make_span()])
    service, _ = build(retriever=retriever)
    await service.execute(Query(text="питання", corpus_ids=[uuid4()]), make_principal())
    assert retriever.calls == 0


async def test_retriever_is_told_which_tiers_it_may_search() -> None:
    retriever = RecordingRetriever([])
    service, _ = build(retriever=retriever)
    await service.execute(
        Query(text="питання"), make_principal(tier=AccessTier.REVIEWED)
    )
    assert retriever.seen_tiers == frozenset(
        {AccessTier.PUBLIC, AccessTier.AUTHENTICATED, AccessTier.REVIEWED}
    )
    assert AccessTier.RESTRICTED not in (retriever.seen_tiers or frozenset())


async def test_leaked_evidence_is_never_answered_from() -> None:
    leaked = make_span(tier=AccessTier.RESTRICTED, score=0.99)
    service, sink = build(retriever=LeakingRetriever([leaked]))
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.REQUIRES_HUMAN_REVIEW
    assert answer.citations == []
    assert any(event == "evidence.tier_violation" for event, _ in sink.events)


async def test_uncited_claim_holds_the_answer_for_review() -> None:
    service, _ = build([make_span()], generator=UncitedGenerator())
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.REQUIRES_HUMAN_REVIEW
    assert answer.citation_coverage == 0.0


async def test_citation_index_outside_the_evidence_set_holds_for_review() -> None:
    service, _ = build([make_span()], generator=OutOfRangeGenerator())
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.REQUIRES_HUMAN_REVIEW


async def test_generator_returning_nothing_holds_for_review() -> None:
    service, _ = build([make_span()], generator=EmptyGenerator())
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.REQUIRES_HUMAN_REVIEW


async def test_generator_failure_never_produces_an_answer() -> None:
    service, _ = build([make_span()], generator=FailingGenerator())
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.REQUIRES_HUMAN_REVIEW
    assert answer.confidence == 0


async def test_coverage_threshold_is_enforced() -> None:
    class HalfCitedGenerator:
        async def compose(
            self, query: Query, evidence: list[EvidenceSpan]
        ) -> list[Claim]:
            del query, evidence
            return [
                Claim(text="З джерелом.", citation_indexes=(0,)),
                Claim(text="Без джерела.", citation_indexes=()),
            ]

    service, _ = build([make_span()], generator=HalfCitedGenerator())
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.REQUIRES_HUMAN_REVIEW
    assert answer.citation_coverage == pytest.approx(0.5)


async def test_confidence_is_the_weakest_supporting_span() -> None:
    service, _ = build([make_span(score=0.95), make_span(score=0.80)])
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.confidence == 0.80


async def test_two_chunks_of_one_version_are_cited_once() -> None:
    version = uuid4()
    service, _ = build([make_span(version_id=version), make_span(version_id=version)])
    answer = await service.execute(Query(text="питання"), make_principal())
    assert len(answer.citations) == 1


async def test_conflicting_equal_authority_sources_are_disclosed() -> None:
    service, _ = build(
        [
            make_span(authority=AuthorityClass.OFFICIAL_UA),
            make_span(authority=AuthorityClass.OFFICIAL_UA),
        ]
    )
    answer = await service.execute(Query(text="питання"), make_principal())
    assert any("розходяться" in limitation for limitation in answer.limitations)


async def test_higher_authority_is_cited_first() -> None:
    analytical = make_span(score=1.0, authority=AuthorityClass.ANALYTICAL)
    official = make_span(score=0.75, authority=AuthorityClass.OFFICIAL_UA)
    service, _ = build([analytical, official])
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.citations[0].chunk_id == official.chunk_id


async def test_every_outcome_records_exactly_one_completion_event() -> None:
    for spans, generator in (
        ([], None),
        ([make_span()], None),
        ([make_span()], UncitedGenerator()),
        ([make_span()], FailingGenerator()),
    ):
        service, sink = build(spans, generator=generator)
        await service.execute(Query(text="питання"), make_principal())
        completions = [event for event, _ in sink.events if event == "answer.completed"]
        assert len(completions) == 1


async def test_audit_payload_carries_the_decision_counts() -> None:
    service, sink = build([make_span(), make_span(review=ReviewState.REJECTED)])
    answer = await service.execute(Query(text="питання"), make_principal())
    _, payload = sink.events[-1]
    assert payload["status"] == "answered"
    assert payload["retrieved"] == 2
    assert payload["eligible"] == 1
    assert payload["trace_id"] == str(answer.trace_id)
    assert payload["subject_id"] == "soldier-1"
    assert payload["principal_tier"] == "public"


async def test_trace_id_is_unique_per_request() -> None:
    service, _ = build([make_span()])
    first = await service.execute(Query(text="питання"), make_principal())
    second = await service.execute(Query(text="питання"), make_principal())
    assert first.trace_id != second.trace_id


async def test_minimum_span_policy_is_enforced() -> None:
    service, _ = build([make_span()], policy=AnswerPolicy(minimum_approved_spans=2))
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE


async def test_evidence_set_is_capped_even_when_the_retriever_overruns() -> None:
    """The cap is the service's own, not a courtesy from the adapter."""

    class OverrunningRetriever:
        def __init__(self, spans: list[EvidenceSpan]) -> None:
            self._spans = spans

        async def search(
            self,
            query: Query,
            allowed_tiers: frozenset[AccessTier],
            allowed_corpora: frozenset[UUID],
            limit: int = 8,
        ) -> list[EvidenceSpan]:
            del query, allowed_tiers, allowed_corpora, limit
            return list(self._spans)

    spans = [make_span() for _ in range(12)]
    service, _ = build(retriever=OverrunningRetriever(spans), policy=AnswerPolicy(maximum_spans=3))
    answer = await service.execute(Query(text="питання"), make_principal())
    assert len(answer.citations) == 3


async def test_integrity_breach_blocks_even_at_acceptable_coverage() -> None:
    """Coverage 0.95 is above the floor; a claim pointing outside the set still blocks.

    Without this case the integrity check and the coverage check are indistinguishable,
    and one of them can be deleted without a single test turning red.
    """

    class MostlyCitedGenerator:
        async def compose(
            self, query: Query, evidence: list[EvidenceSpan]
        ) -> list[Claim]:
            del query
            good = [Claim(text=f"твердження {i}", citation_indexes=(0,)) for i in range(19)]
            return [*good, Claim(text="поза набором", citation_indexes=(len(evidence) + 7,))]

    service, _ = build([make_span()], generator=MostlyCitedGenerator())
    answer = await service.execute(Query(text="питання"), make_principal())
    assert answer.citation_coverage == pytest.approx(0.95)
    assert answer.status is AnswerStatus.REQUIRES_HUMAN_REVIEW


async def test_audit_records_the_principal_tier_that_actually_asked() -> None:
    service, sink = build([make_span(tier=AccessTier.REVIEWED)])
    await service.execute(
        Query(text="питання"), make_principal(tier=AccessTier.REVIEWED, subject_id="rev-9")
    )
    _, payload = sink.events[-1]
    assert payload["principal_tier"] == "reviewed"
    assert payload["subject_id"] == "rev-9"


async def test_stub_retriever_honours_the_tier_argument() -> None:
    """The development adapter is held to the same rule as a production index."""
    retriever = InMemoryRetriever(
        [make_span(tier=AccessTier.RESTRICTED), make_span(tier=AccessTier.PUBLIC)]
    )
    found = await retriever.search(
        Query(text="питання"), frozenset({AccessTier.PUBLIC}), frozenset({CORPUS}), limit=8
    )
    assert [span.access_tier for span in found] == [AccessTier.PUBLIC]
