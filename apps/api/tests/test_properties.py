"""Property-based tests.

The example tests state what the system does in named situations. These state what
must hold in every situation, including the ones nobody thought to name: generate a
corpus and a reader at random, run the real pipeline, and check the invariants that
the product promise reduces to.

Hypothesis shrinks a failure to its smallest form, so a violation arrives as the
minimal corpus that produces it rather than as a wall of random data.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from conftest import NOW, make_span
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from korpus.application.answer_query import AnswerPolicy, AnswerQuery
from korpus.application.ingestion import SourceDescriptor, chunk_document
from korpus.domain.access import TIER_ORDER, Principal, allowed_tiers
from korpus.domain.authority import AUTHORITY_RANK, NON_GOVERNING
from korpus.domain.models import (
    AccessTier,
    AnswerStatus,
    AuthorityClass,
    EvidenceSpan,
    Query,
    ReviewState,
)
from korpus.infrastructure.in_memory import (
    EvidenceBoundStubGenerator,
    FixedClock,
    InMemoryAuditSink,
)
from korpus.infrastructure.lexical import LexicalRetriever

CORPORA = [UUID(int=index) for index in range(1, 4)]
WORDS = ["порядок", "евакуації", "поранених", "зберігання", "пального", "зв'язку"]

PROFILE = settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@st.composite
def spans(draw: st.DrawFn) -> EvidenceSpan:
    text = " ".join(draw(st.lists(st.sampled_from(WORDS), min_size=1, max_size=4)))
    return make_span(
        text=text,
        quote=text,
        corpus_id=draw(st.sampled_from(CORPORA)),
        tier=draw(st.sampled_from(list(AccessTier))),
        review=draw(st.sampled_from(list(ReviewState))),
        authority=draw(st.sampled_from(list(AuthorityClass))),
        score=1.0,
    )


@st.composite
def principals(draw: st.DrawFn) -> Principal:
    return Principal(
        subject_id="generated",
        tier=draw(st.sampled_from(list(AccessTier))),
        authorized_corpora=frozenset(
            draw(st.lists(st.sampled_from(CORPORA), max_size=3, unique=True))
        ),
    )


def answer_for(
    corpus: list[EvidenceSpan], principal: Principal, question: str, requested: list[UUID]
) -> tuple[AnswerStatus, list[EvidenceSpan], object]:
    service = AnswerQuery(
        retriever=LexicalRetriever(corpus),
        generator=EvidenceBoundStubGenerator(),
        audit=InMemoryAuditSink(),
        policy=AnswerPolicy(),
        clock=FixedClock(NOW),
    )
    answer = asyncio.run(
        service.execute(Query(text=question, corpus_ids=requested), principal)
    )
    return answer.status, corpus, answer


@PROFILE
@given(
    corpus=st.lists(spans(), max_size=8),
    principal=principals(),
    question=st.lists(st.sampled_from(WORDS), min_size=1, max_size=3),
)
def test_no_answer_ever_cites_material_the_reader_may_not_read(
    corpus: list[EvidenceSpan], principal: Principal, question: list[str]
) -> None:
    """The invariant the whole access model exists to produce."""
    _, _, answer = answer_for(corpus, principal, " ".join(question), [])
    cited = {citation.chunk_id for citation in answer.citations}
    by_chunk = {span.chunk_id: span for span in corpus}
    for chunk_id in cited:
        span = by_chunk[chunk_id]
        assert TIER_ORDER[span.access_tier] <= TIER_ORDER[principal.tier]
        assert span.corpus_id in principal.authorized_corpora


@PROFILE
@given(
    corpus=st.lists(spans(), max_size=8),
    principal=principals(),
    question=st.lists(st.sampled_from(WORDS), min_size=1, max_size=3),
)
def test_an_answered_response_is_fully_cited_and_fully_eligible(
    corpus: list[EvidenceSpan], principal: Principal, question: list[str]
) -> None:
    _, _, answer = answer_for(corpus, principal, " ".join(question), [])
    if answer.status is not AnswerStatus.ANSWERED:
        return
    assert answer.claims
    assert answer.citation_coverage == 1.0
    assert all(claim.citation_indexes for claim in answer.claims)
    assert all(
        index in range(len(answer.citations))
        for claim in answer.claims
        for index in claim.citation_indexes
    )
    by_chunk = {span.chunk_id: span for span in corpus}
    for citation in answer.citations:
        span = by_chunk[citation.chunk_id]
        assert span.review_state is ReviewState.APPROVED
        assert span.authority not in NON_GOVERNING
        assert span.superseded_by is None


@PROFILE
@given(
    corpus=st.lists(spans(), max_size=6),
    principal=principals(),
    question=st.lists(st.sampled_from(WORDS), min_size=1, max_size=3),
)
def test_a_refusal_never_carries_evidence(
    corpus: list[EvidenceSpan], principal: Principal, question: list[str]
) -> None:
    status, _, answer = answer_for(corpus, principal, " ".join(question), [])
    if status in (AnswerStatus.INSUFFICIENT_EVIDENCE, AnswerStatus.ACCESS_DENIED):
        assert answer.citations == []
        assert answer.claims == []
        assert answer.confidence == 0


@PROFILE
@given(
    corpus=st.lists(spans(), max_size=6),
    principal=principals(),
    requested=st.lists(st.sampled_from(CORPORA), max_size=2, unique=True),
    question=st.lists(st.sampled_from(WORDS), min_size=1, max_size=3),
)
def test_requesting_an_unheld_corpus_is_always_a_denial(
    corpus: list[EvidenceSpan],
    principal: Principal,
    requested: list[UUID],
    question: list[str],
) -> None:
    status, _, answer = answer_for(corpus, principal, " ".join(question), requested)
    unheld = [c for c in requested if c not in principal.authorized_corpora]
    if unheld:
        assert status is AnswerStatus.ACCESS_DENIED
        assert answer.citations == []


@PROFILE
@given(
    corpus=st.lists(spans(), max_size=8),
    principal=principals(),
    question=st.text(max_size=200),
)
def test_the_pipeline_never_raises(
    corpus: list[EvidenceSpan], principal: Principal, question: str
) -> None:
    """Any input a validated Query can hold must produce an answer, not an exception."""
    text = question.strip() or "порядок"
    if len(text) > 4000:
        text = text[:4000]
    if len(text) < 3:
        text = text + "..."
    status, _, _ = answer_for(corpus, principal, text, [])
    assert isinstance(status, AnswerStatus)


@PROFILE
@given(
    corpus=st.lists(spans(), max_size=8),
    tier=st.sampled_from(list(AccessTier)),
    grant=st.lists(st.sampled_from(CORPORA), max_size=3, unique=True),
    question=st.lists(st.sampled_from(WORDS), min_size=1, max_size=3),
)
def test_retrieval_never_leaves_the_authorized_bounds(
    corpus: list[EvidenceSpan],
    tier: AccessTier,
    grant: list[UUID],
    question: list[str],
) -> None:
    retriever = LexicalRetriever(corpus)
    found = asyncio.run(
        retriever.search(
            Query(text=" ".join(question)), allowed_tiers(tier), frozenset(grant)
        )
    )
    assert all(span.access_tier in allowed_tiers(tier) for span in found)
    assert all(span.corpus_id in set(grant) for span in found)


@PROFILE
@given(
    text=st.text(min_size=1, max_size=500),
    revision=st.one_of(st.none(), st.text(min_size=1, max_size=8)),
)
def test_chunking_is_reproducible(text: str, revision: str | None) -> None:
    """The same bytes must always produce the same chunk identity, on any machine."""
    descriptor = SourceDescriptor(
        corpus_id=CORPORA[0],
        title="Настанова",
        authority=AuthorityClass.OFFICIAL_UA,
        revision=revision,
    )
    first = chunk_document(text, descriptor)
    second = chunk_document(text, descriptor)
    assert [span.chunk_id for span in first] == [span.chunk_id for span in second]


@PROFILE
@given(corpus=st.lists(spans(), min_size=1, max_size=8))
def test_precedence_never_places_a_weaker_authority_first(
    corpus: list[EvidenceSpan],
) -> None:
    from korpus.domain.authority import order_by_precedence

    ordered = order_by_precedence(corpus)
    ranks = [AUTHORITY_RANK[span.authority] for span in ordered]
    assert ranks == sorted(ranks)


@PROFILE
@given(tier=st.sampled_from(list(AccessTier)))
def test_a_reader_sees_its_own_tier_and_nothing_above(tier: AccessTier) -> None:
    visible = allowed_tiers(tier)
    assert tier in visible
    assert all(TIER_ORDER[seen] <= TIER_ORDER[tier] for seen in visible)


def test_generated_corpora_actually_exercise_the_answered_path() -> None:
    """Guards the generators themselves: a property suite that only ever abstains
    proves nothing. One concrete corpus must reach `answered` through the same path."""
    corpus = [
        make_span(
            text="порядок евакуації",
            quote="порядок евакуації",
            corpus_id=CORPORA[0],
            tier=AccessTier.PUBLIC,
            review=ReviewState.APPROVED,
            authority=AuthorityClass.OFFICIAL_UA,
        )
    ]
    principal = Principal(
        subject_id="s", tier=AccessTier.PUBLIC, authorized_corpora=frozenset({CORPORA[0]})
    )
    status, _, _ = answer_for(corpus, principal, "порядок евакуації", [])
    assert status is AnswerStatus.ANSWERED
