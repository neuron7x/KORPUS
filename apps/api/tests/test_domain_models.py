"""Model invariants.

Each test names the malformed value that must be rejected. Validation that nothing
exercises is decoration; these are the assertions that make it load-bearing.
"""

from uuid import uuid4

import pytest
from conftest import make_span
from pydantic import ValidationError

from korpus.domain.models import Citation, Claim, EvidenceSpan, Query


def test_citation_rejects_empty_quote() -> None:
    with pytest.raises(ValidationError):
        Citation(document_id=uuid4(), chunk_id=uuid4(), title="Наказ", quote="")


def test_citation_rejects_empty_title() -> None:
    with pytest.raises(ValidationError):
        Citation(document_id=uuid4(), chunk_id=uuid4(), title="", quote="текст")


def test_citation_rejects_page_zero() -> None:
    with pytest.raises(ValidationError):
        Citation(
            document_id=uuid4(), chunk_id=uuid4(), title="Наказ", page=0, quote="текст"
        )


def test_citation_rejects_overlong_quote() -> None:
    with pytest.raises(ValidationError):
        Citation(
            document_id=uuid4(), chunk_id=uuid4(), title="Наказ", quote="я" * 1201
        )


def test_citation_is_immutable() -> None:
    citation = make_span().citation
    with pytest.raises(ValidationError):
        citation.title = "інша назва"  # type: ignore[misc]


def test_evidence_span_rejects_score_above_one() -> None:
    with pytest.raises(ValidationError):
        make_span(score=1.01)


def test_evidence_span_rejects_negative_score() -> None:
    with pytest.raises(ValidationError):
        make_span(score=-0.01)


def test_evidence_span_accepts_the_closed_unit_interval() -> None:
    assert make_span(score=0.0).retrieval_score == 0.0
    assert make_span(score=1.0).retrieval_score == 1.0


def test_evidence_span_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        make_span(text="")


def test_evidence_span_is_immutable() -> None:
    span = make_span()
    with pytest.raises(ValidationError):
        span.retrieval_score = 0.1  # type: ignore[misc]


def test_query_rejects_two_character_text() -> None:
    with pytest.raises(ValidationError):
        Query(text="як")


def test_query_accepts_three_character_text() -> None:
    assert Query(text="як?").text == "як?"


def test_query_rejects_overlong_text() -> None:
    with pytest.raises(ValidationError):
        Query(text="я" * 4001)


def test_query_rejects_malformed_locale() -> None:
    with pytest.raises(ValidationError):
        Query(text="питання", locale="Ukrainian")


def test_query_accepts_language_only_locale() -> None:
    assert Query(text="питання", locale="en").locale == "en"


def test_query_rejects_more_than_twenty_corpora() -> None:
    with pytest.raises(ValidationError):
        Query(text="питання", corpus_ids=[uuid4() for _ in range(21)])


def test_query_refuses_a_client_supplied_tier() -> None:
    """The spoofing test: a caller must not be able to name its own access tier."""
    with pytest.raises(ValidationError):
        Query(text="питання", user_tier="restricted")  # type: ignore[call-arg]


def test_query_refuses_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Query(text="питання", role="commander")  # type: ignore[call-arg]


def test_claim_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        Claim(text="")


def test_claim_without_citations_is_representable_and_unsupported() -> None:
    """Deliberate: the verifier must be able to see an uncited claim to reject it."""
    assert Claim(text="твердження").citation_indexes == ()


def test_naive_validity_timestamp_is_read_as_utc() -> None:
    """A tz-naive value used to crash the whole request when compared to the clock."""
    from datetime import UTC, datetime

    span = make_span(valid_until=datetime(2026, 8, 2, 12, 0))
    assert span.valid_until is not None
    assert span.valid_until.tzinfo is not None
    assert span.valid_until == datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def test_aware_validity_timestamp_is_left_alone() -> None:
    from datetime import UTC, datetime

    moment = datetime(2026, 8, 2, 15, 0, tzinfo=UTC)
    assert make_span(valid_until=moment).valid_until == moment


def test_evidence_span_requires_a_corpus() -> None:
    with pytest.raises(ValidationError):
        EvidenceSpan(  # type: ignore[call-arg]
            citation=make_span().citation,
            chunk_id=uuid4(),
            document_id=uuid4(),
            document_version_id=uuid4(),
            text="текст",
            retrieval_score=0.9,
            access_tier="public",
            review_state="approved",
            authority="official_ua",
        )


def test_evidence_span_requires_chunk_identity() -> None:
    with pytest.raises(ValidationError):
        EvidenceSpan(  # type: ignore[call-arg]
            citation=make_span().citation,
            document_id=uuid4(),
            document_version_id=uuid4(),
            text="текст",
            retrieval_score=0.9,
            access_tier="public",
            review_state="approved",
            authority="official_ua",
        )
