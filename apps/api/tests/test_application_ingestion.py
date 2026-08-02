"""Ingestion: what a chunk is, and why the same file twice is the same corpus."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from korpus.application.ingestion import (
    MAX_QUOTE,
    SourceDescriptor,
    chunk_document,
    content_hash,
    read_source,
    split_paragraphs,
)
from korpus.domain.models import AccessTier, AuthorityClass, ReviewState

DOCUMENT = """Порядок евакуації поранених

Евакуація здійснюється за принципом стабілізації перед переміщенням.

Черговість визначає медичний працівник за станом пораненого, а не за званням.
"""


def descriptor(**overrides: object) -> SourceDescriptor:
    base: dict[str, object] = {
        "corpus_id": uuid4(),
        "title": "Настанова",
        "authority": AuthorityClass.OFFICIAL_UA,
    }
    base.update(overrides)
    return SourceDescriptor(**base)  # type: ignore[arg-type]


def test_paragraphs_are_the_unit_a_reader_can_find() -> None:
    assert len(split_paragraphs(DOCUMENT)) == 3


def test_blank_input_produces_no_chunks() -> None:
    assert chunk_document("   \n\n  ", descriptor()) == []


def test_the_same_file_ingested_twice_produces_identical_identity() -> None:
    """Idempotency lives here: ids come from content, not from insertion order."""
    first = chunk_document(DOCUMENT, descriptor())
    second = chunk_document(DOCUMENT, descriptor())
    assert [s.chunk_id for s in first] == [s.chunk_id for s in second]
    assert first[0].document_id == second[0].document_id
    assert first[0].document_version_id == second[0].document_version_id


def test_changed_content_is_a_different_document() -> None:
    original = chunk_document(DOCUMENT, descriptor())
    edited = chunk_document(DOCUMENT.replace("стабілізації", "переміщення"), descriptor())
    assert original[0].document_id != edited[0].document_id


def test_a_revision_is_a_different_version_of_the_same_document() -> None:
    first = chunk_document(DOCUMENT, descriptor(revision="1"))
    second = chunk_document(DOCUMENT, descriptor(revision="2"))
    assert first[0].document_id == second[0].document_id
    assert first[0].document_version_id != second[0].document_version_id


def test_ingested_material_is_quarantined_until_a_reviewer_acts() -> None:
    spans = chunk_document(DOCUMENT, descriptor())
    assert all(span.review_state is ReviewState.QUARANTINED for span in spans)


def test_the_reviewer_decision_is_carried_onto_every_chunk() -> None:
    spans = chunk_document(
        DOCUMENT,
        descriptor(review_state=ReviewState.APPROVED, access_tier=AccessTier.REVIEWED),
    )
    assert all(span.review_state is ReviewState.APPROVED for span in spans)
    assert all(span.access_tier is AccessTier.REVIEWED for span in spans)


def test_a_long_paragraph_is_quoted_within_the_citation_limit() -> None:
    long_text = "я" * (MAX_QUOTE + 500)
    span = chunk_document(long_text, descriptor())[0]
    assert len(span.citation.quote) <= MAX_QUOTE
    assert span.text == long_text  # the evidence keeps the full paragraph


def test_content_hash_is_stable_and_sensitive() -> None:
    assert content_hash("а") == content_hash("а")
    assert content_hash("а") != content_hash("б")


def test_binary_formats_are_refused_rather_than_half_extracted(tmp_path: Path) -> None:
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.7 binary")
    with pytest.raises(ValueError, match=r"only \.txt and \.md"):
        read_source(pdf)


def test_markdown_and_text_are_read(tmp_path: Path) -> None:
    for name in ("a.md", "b.txt"):
        path = tmp_path / name
        path.write_text(DOCUMENT, encoding="utf-8")
        assert read_source(path).startswith("Порядок")


def test_every_chunk_carries_the_corpus_it_belongs_to() -> None:
    corpus = uuid4()
    spans = chunk_document(DOCUMENT, descriptor(corpus_id=corpus))
    assert {span.corpus_id for span in spans} == {corpus}


def test_citation_points_at_the_chunk_not_the_file() -> None:
    span = chunk_document(DOCUMENT, descriptor())[0]
    assert span.citation.chunk_id == span.chunk_id
