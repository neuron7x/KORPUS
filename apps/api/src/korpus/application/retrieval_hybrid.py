"""Hybrid retrieval execution with bounded candidate and evidence budgets."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from typing import Protocol, cast
from uuid import UUID

from korpus.application.ports import Repository
from korpus.application.retrieval_math import (
    BM25Parameters,
    RetrievalWeights,
    ScoredCandidate,
    score_candidates,
)
from korpus.domain.models import (
    AuthorityClass,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    RetrievedEvidence,
)

CandidateRow = tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]


class SemanticSource(Protocol):
    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int,
    ) -> list[tuple[UUID, float]]: ...


class Diversifier(Protocol):
    def __call__(
        self,
        evidence: list[RetrievedEvidence],
        *,
        limit: int,
        diversity_lambda: float,
        per_version_cap: int,
        authority_priors: dict[AuthorityClass, float],
    ) -> list[RetrievedEvidence]: ...


def _initial_candidates(
    repository: Repository,
    contextual_enabled: bool,
    approved_aliases: dict[str, tuple[str, ...]],
    identity: Identity,
    corpus_ids: frozenset[str],
    as_of: date,
    text: str,
    budget: int,
) -> list[CandidateRow]:
    contextual = getattr(repository, "search_contextual_retrievable_spans", None)
    if contextual_enabled and callable(contextual):
        return cast(
            list[CandidateRow],
            contextual(
                identity, corpus_ids, as_of, text, budget, approved_aliases=approved_aliases
            ),
        )
    return repository.search_retrievable_spans(identity, corpus_ids, as_of, text, budget)


def execute_hybrid_search_impl(
    *,
    repository: Repository,
    parameters: BM25Parameters,
    candidate_budget: int,
    weights: RetrievalWeights,
    timeout_ms: int,
    semantic_source: SemanticSource | None,
    semantic_available: bool,
    authority_priors: dict[AuthorityClass, float],
    contextual_projection_enabled: bool,
    approved_aliases: dict[str, tuple[str, ...]],
    identity: Identity,
    text: str,
    corpus_ids: frozenset[str],
    as_of: date,
    limit: int,
    semantic_enabled: bool | None,
    temporal_relevance: Callable[[date, date | None, date | None], float],
    diversify: Diversifier,
    diversity_lambda: float,
    per_version_cap: int,
    semantic_candidates: Callable[..., tuple[list[CandidateRow], dict[str, float]]],
    scoring_texts: Callable[[list[CandidateRow], bool, dict[str, tuple[str, ...]]], list[str]],
    materialize_evidence: Callable[
        [list[CandidateRow], list[ScoredCandidate], dict[AuthorityClass, float]],
        list[RetrievedEvidence],
    ],
    deadline_error: type[TimeoutError],
) -> list[RetrievedEvidence]:
    started = time.monotonic()
    candidates = _initial_candidates(
        repository,
        contextual_projection_enabled,
        approved_aliases,
        identity,
        corpus_ids,
        as_of,
        text,
        candidate_budget,
    )
    semantic_by_span: dict[str, float] = {}
    use_semantic = semantic_available if semantic_enabled is None else semantic_enabled
    if use_semantic:
        if semantic_source is None:
            raise deadline_error("semantic retrieval is enabled without a semantic source")
        candidates, semantic_by_span = semantic_candidates(
            repository,
            semantic_source,
            candidates,
            identity,
            text,
            corpus_ids,
            as_of,
            candidate_budget,
        )
    if not candidates:
        if (time.monotonic() - started) * 1000 > timeout_ms:
            raise deadline_error("candidate retrieval exceeded deadline")
        return []
    candidates = list({str(item[0].id): item for item in candidates}.values())
    components = score_candidates(
        text,
        scoring_texts(candidates, contextual_projection_enabled, approved_aliases),
        [version.authority.value.startswith("official_") for _, _, version in candidates],
        parameters,
        authority_scores=[authority_priors[version.authority] for _, _, version in candidates],
        semantic_scores=[semantic_by_span.get(str(span.id), 0.0) for span, _, _ in candidates],
        temporal_scores=[
            temporal_relevance(as_of, version.publication_date, version.effective_from)
            for _, _, version in candidates
        ],
        weights=weights,
    )
    return diversify(
        materialize_evidence(candidates, components, authority_priors),
        limit=limit,
        diversity_lambda=diversity_lambda,
        per_version_cap=per_version_cap,
        authority_priors=authority_priors,
    )
