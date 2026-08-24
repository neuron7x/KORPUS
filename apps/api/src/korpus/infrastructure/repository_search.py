"""Bounded lexical and trusted-context candidate search for ``SqlRepository``."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import or_

from korpus.application.retrieval_math import candidate_terms
from korpus.infrastructure import retrieval_queries
from korpus.infrastructure.schema import documents, spans, versions


def search_retrievable_spans(
    repository: Any,
    identity: Any,
    corpus_ids: frozenset[str],
    as_of: date,
    query: str,
    candidate_limit: int,
) -> list[tuple[Any, Any, Any]]:
    if candidate_limit < 1:
        raise ValueError("candidate_limit must be positive")
    corpora = corpus_ids.intersection(identity.corpora)
    if not corpora:
        return []
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, identity)
        span_ids = repository._candidate_span_ids(
            identity, corpora, as_of, query, candidate_limit * 4, connection
        )
        if not span_ids:
            return []
        statement = retrieval_queries.retrievable_projection(identity, corpora, as_of).where(
            spans.c.id.in_(span_ids)
        )
        rows = connection.execute(statement).mappings().all()
    by_id = {row["span_id"]: row for row in rows}
    ordered = [by_id[span_id] for span_id in span_ids if span_id in by_id]
    return retrieval_queries.materialize_current(ordered, as_of, limit=candidate_limit)


def _context_terms(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.casefold() for value, _ in candidate_terms(query)))


def _alias_document_ids(
    terms: tuple[str, ...], approved_aliases: dict[str, tuple[str, ...]] | None
) -> list[str]:
    query_terms = set(terms)
    matches: list[str] = []
    for document_id, aliases in sorted((approved_aliases or {}).items()):
        alias_terms = {value.casefold() for alias in aliases for value, _ in candidate_terms(alias)}
        if query_terms.intersection(alias_terms):
            matches.append(str(document_id))
    return matches


def _context_predicates(terms: tuple[str, ...], alias_document_ids: list[str]) -> list[Any]:
    columns = (
        documents.c.canonical_title,
        spans.c.section,
        documents.c.corpus_id,
        documents.c.issuer,
        documents.c.jurisdiction,
        documents.c.document_type,
        versions.c.revision,
    )
    predicates = [column.ilike(f"%{term}%") for term in terms for column in columns]
    if alias_document_ids:
        predicates.append(documents.c.id.in_(alias_document_ids))
    return predicates


def search_contextual_retrievable_spans(
    repository: Any,
    identity: Any,
    corpus_ids: frozenset[str],
    as_of: date,
    query: str,
    candidate_limit: int,
    *,
    approved_aliases: dict[str, tuple[str, ...]] | None = None,
) -> list[tuple[Any, Any, Any]]:
    """Fill only unused lexical budget from deterministic trusted metadata."""
    if candidate_limit < 1:
        raise ValueError("candidate_limit must be positive")
    baseline = search_retrievable_spans(
        repository, identity, corpus_ids, as_of, query, candidate_limit
    )
    corpora = corpus_ids.intersection(identity.corpora)
    terms = _context_terms(query)
    if len(baseline) >= candidate_limit or not corpora or not terms:
        return baseline
    predicates = _context_predicates(terms, _alias_document_ids(terms, approved_aliases))
    if not predicates:
        return baseline
    baseline_ids = {str(span.id) for span, _, _ in baseline}
    statement = retrieval_queries.retrievable_projection(identity, corpora, as_of).where(
        or_(*predicates)
    )
    if baseline_ids:
        statement = statement.where(spans.c.id.not_in(sorted(baseline_ids)))
    remaining = candidate_limit - len(baseline)
    statement = statement.limit(remaining)
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, identity)
        rows = connection.execute(statement).mappings().all()
    contextual = retrieval_queries.materialize_current(rows, as_of, limit=remaining)
    return [*baseline, *contextual]
