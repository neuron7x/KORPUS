"""Lexical retrieval: the deterministic floor a dense retriever has to beat."""

from uuid import uuid4

import pytest
from conftest import make_span

from korpus.domain.models import AccessTier, Query
from korpus.infrastructure.lexical import LexicalRetriever, coverage_score, normalize

ALL_TIERS = frozenset(AccessTier)
PUBLIC_ONLY = frozenset({AccessTier.PUBLIC})


def test_normalize_casefolds_and_drops_stopwords() -> None:
    assert normalize("Що визначає ПОРЯДОК дій") == ["визначає", "порядок", "дій"]


def test_normalize_strips_punctuation_but_keeps_digits() -> None:
    assert normalize("пункт 4.2, абзац-3") == ["пункт", "4", "2", "абзац", "3"]


def test_coverage_score_of_empty_query_is_zero() -> None:
    assert coverage_score([], ["будь", "що"]) == 0.0


def test_coverage_score_is_bounded_by_one() -> None:
    assert coverage_score(["а"], ["а", "а", "а"]) == 1.0


def test_coverage_score_is_the_fraction_of_matched_terms() -> None:
    assert coverage_score(["а", "б"], ["а", "в"]) == pytest.approx(0.5)


async def test_query_text_actually_selects_documents() -> None:
    matching = make_span(text="Порядок евакуації поранених", quote="Порядок евакуації.")
    other = make_span(text="Правила зберігання пального", quote="Зберігання пального.")
    retriever = LexicalRetriever([matching, other])
    found = await retriever.search(Query(text="порядок евакуації"), ALL_TIERS)
    assert [span.chunk_id for span in found] == [matching.chunk_id]


async def test_a_query_matching_nothing_returns_nothing() -> None:
    retriever = LexicalRetriever([make_span(text="Правила зберігання пального")])
    assert await retriever.search(Query(text="радіочастотний план"), ALL_TIERS) == []


async def test_stopword_only_query_matches_nothing() -> None:
    retriever = LexicalRetriever([make_span(text="Правила зберігання пального")])
    assert await retriever.search(Query(text="і не та"), ALL_TIERS) == []


async def test_score_reflects_term_coverage() -> None:
    span = make_span(text="Порядок евакуації поранених з переднього краю")
    retriever = LexicalRetriever([span])
    found = await retriever.search(Query(text="порядок евакуації"), ALL_TIERS)
    assert found[0].retrieval_score == pytest.approx(1.0)
    partial = await retriever.search(Query(text="порядок ремонту"), ALL_TIERS)
    assert partial[0].retrieval_score == pytest.approx(0.5)


async def test_tiers_are_filtered_inside_the_index() -> None:
    restricted = make_span(text="таємний порядок", tier=AccessTier.RESTRICTED)
    public = make_span(text="відкритий порядок", tier=AccessTier.PUBLIC)
    retriever = LexicalRetriever([restricted, public])
    found = await retriever.search(Query(text="порядок"), PUBLIC_ONLY)
    assert [span.chunk_id for span in found] == [public.chunk_id]


async def test_requested_corpus_filters_out_unassigned_documents() -> None:
    corpus = uuid4()
    inside = make_span(text="порядок дій")
    outside = make_span(text="порядок дій")
    retriever = LexicalRetriever([inside, outside], corpus_of={inside.document_id: corpus})
    found = await retriever.search(Query(text="порядок", corpus_ids=[corpus]), ALL_TIERS)
    assert [span.chunk_id for span in found] == [inside.chunk_id]


async def test_results_are_ordered_by_score_then_chunk_id() -> None:
    strong = make_span(text="порядок евакуації поранених")
    weak = make_span(text="порядок зберігання")
    retriever = LexicalRetriever([weak, strong])
    found = await retriever.search(Query(text="порядок евакуації"), ALL_TIERS)
    assert found[0].chunk_id == strong.chunk_id


async def test_limit_is_honoured() -> None:
    spans = [make_span(text="порядок дій") for _ in range(5)]
    retriever = LexicalRetriever(spans)
    assert len(await retriever.search(Query(text="порядок"), ALL_TIERS, limit=2)) == 2


async def test_search_is_deterministic_across_repeated_calls() -> None:
    spans = [make_span(text="порядок дій") for _ in range(4)]
    retriever = LexicalRetriever(spans)
    first = await retriever.search(Query(text="порядок"), ALL_TIERS)
    second = await retriever.search(Query(text="порядок"), ALL_TIERS)
    assert [s.chunk_id for s in first] == [s.chunk_id for s in second]


async def test_a_span_added_with_a_corpus_is_filterable_by_it() -> None:
    corpus = uuid4()
    inside = make_span(text="порядок дій")
    retriever = LexicalRetriever()
    retriever.add(inside, corpus_id=corpus)
    retriever.add(make_span(text="порядок дій"))
    found = await retriever.search(Query(text="порядок", corpus_ids=[corpus]), ALL_TIERS)
    assert [span.chunk_id for span in found] == [inside.chunk_id]


async def test_added_spans_are_searchable_and_counted() -> None:
    retriever = LexicalRetriever()
    assert retriever.size == 0
    retriever.add(make_span(text="порядок дій"))
    assert retriever.size == 1
    assert len(await retriever.search(Query(text="порядок"), ALL_TIERS)) == 1
