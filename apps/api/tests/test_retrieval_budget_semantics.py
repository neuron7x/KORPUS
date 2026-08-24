"""The budget decides what to start, not what to throw away.

Measured against the running deployment on 2026-08-06: at eight concurrent readers, 62 of
117 answers came back `retrieval_deadline_exceeded`. The reader waited the full two
seconds and was then told the corpus held nothing — the one outcome dominated by every
other, because the work had already been done and was discarded on the way out.

The cause was a wall-clock check placed *after* the search returned. An answer is
CPU-bound Python and uvicorn serves it on a thread pool, so eight concurrent questions
queued behind one interpreter; the elapsed time each thread measured included the others'
work. The check was reporting contention as an unfinished search, and paying for the
search twice over — once to run it, once to lose it.

What the budget must still do is refuse when there is nothing to keep. Overrunning with no
candidates means the search genuinely did not finish looking, and "no basis" about a
question nobody finished searching is the assertion this system exists not to make.

The second check, after re-ranking, is gone entirely: everything is complete by that line,
so raising there costs the reader their answer and saves no work at all.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import pytest
from korpus.application.retrieval import (
    AUTHORITY_PRIOR,
    BM25Parameters,
    HybridLexicalRetriever,
    RetrievalDeadlineExceeded,
    RetrievalWeights,
)
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    ReviewState,
)

IDENTITY = Identity(
    subject="reader",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public"}),
)


class _SlowRepository:
    """A repository that always overruns the budget, returning what it was given."""

    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def search_retrievable_spans(self, *arguments: Any, **keywords: Any) -> list[Any]:
        time.sleep(0.05)
        return list(self.rows)

    def get_retrievable_spans_by_ids(self, *arguments: Any, **keywords: Any) -> list[Any]:
        return []


def _retriever(rows: list[Any]) -> HybridLexicalRetriever:
    return HybridLexicalRetriever(
        _SlowRepository(rows),  # type: ignore[arg-type]
        parameters=BM25Parameters(),
        candidate_budget=16,
        weights=RetrievalWeights(),
        diversity_lambda=0.8,
        per_version_cap=1,
        # Ten milliseconds: the repository above always takes longer, so every call in
        # this module is an overrun and the tests differ only in what was found.
        timeout_ms=10,
        semantic_source=None,
        authority_priors=AUTHORITY_PRIOR,
    )


def _search(retriever: HybridLexicalRetriever) -> list[Any]:
    return retriever.search(IDENTITY, "маскування позиції", frozenset({"public"}), date.today())


def test_an_overrun_with_nothing_found_is_still_refused() -> None:
    """The half that must not be lost: an unfinished search is not an established absence."""
    with pytest.raises(RetrievalDeadlineExceeded):
        _search(_retriever([]))


def _row() -> tuple[Any, Any, Any]:
    """One (span, document, version) triple, shaped as the projection returns them."""
    document = DocumentRecord(
        canonical_title="Настанова",
        corpus_id="public",
        issuer="Не встановлено",
        jurisdiction="UA",
        document_type="reference",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1",
        source_hash="a" * 64,
        object_key="objects/a",
        mime_type="text/plain",
        publication_date=date(2024, 1, 1),
        authority=AuthorityClass.ANALYTICAL,
        review_state=ReviewState.APPROVED,
    )
    span = EvidenceSpanRecord(
        version_id=version.id,
        ordinal=0,
        page=1,
        text="Маскування позиції виконується табельними засобами.",
    )
    return span, document, version


def test_an_overrun_that_found_candidates_returns_them() -> None:
    """Discarding finished work charges the reader for it twice and answers nothing."""
    results = _search(_retriever([_row()]))

    assert results, "candidates were retrieved and then thrown away"


def test_nothing_found_within_budget_is_an_empty_answer_not_a_refusal() -> None:
    """The control: an empty corpus is a different event from an unfinished search."""

    class _Fast(_SlowRepository):
        def search_retrievable_spans(self, *arguments: Any, **keywords: Any) -> list[Any]:
            return []

    retriever = _retriever([])
    retriever.repository = _Fast([])  # type: ignore[assignment]

    assert _search(retriever) == []
