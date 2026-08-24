from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from typing import Any

from korpus.application.contextual_projection import build_contextual_projection
from korpus.application.retrieval_math import score_candidates
from korpus.domain.models import Identity, RetrievedEvidence


class ExecutionDeadlineExceeded(TimeoutError):
    pass


class ExecutionUnavailable(RuntimeError):
    pass


def _semantic_candidates(
    repository: Any,
    semantic_source: Any,
    candidates: list[Any],
    identity: Identity,
    text: str,
    corpus_ids: frozenset[str],
    as_of: date,
    candidate_budget: int,
) -> tuple[list[Any], dict[str, float]]:
    try:
        hits = semantic_source.search(identity, text, corpus_ids, as_of, candidate_budget)
    except Exception as exc:
        raise ExecutionUnavailable("required semantic retrieval is unavailable") from exc
    scores = {str(span_id): score for span_id, score in hits}
    known = {str(span.id) for span, _, _ in candidates}
    missing = [span_id for span_id, _ in hits if str(span_id) not in known]
    if missing:
        candidates.extend(repository.get_retrievable_spans_by_ids(identity, corpus_ids, as_of, missing))
    return candidates, scores


def _scoring_texts(
    candidates: list[Any],
    contextual_projection_enabled: bool,
    approved_aliases: dict[str, tuple[str, ...]],
) -> list[str]:
    if not contextual_projection_enabled:
        return [span.text for span, _, _ in candidates]
    return [
        build_contextual_projection(
            span, document, version,
            approved_aliases=approved_aliases.get(str(document.id), ()),
        ).retrieval_text
        for span, document, version in candidates
    ]


def _materialize_evidence(
    candidates: list[Any],
    components: list[Any],
    authority_priors: dict[Any, float],
) -> list[RetrievedEvidence]:
    output: list[RetrievedEvidence] = []
    for scored in components:
        span, document, version = candidates[scored.index]
        if scored.normalized_score == 0:
            continue
        output.append(RetrievedEvidence(
            span=span, document=document, version=version,
            score=scored.normalized_score, query_coverage=scored.query_coverage,
            lexical_score=scored.lexical_score, semantic_score=scored.semantic_score,
            character_score=scored.character_score, authority_bonus=scored.authority_score,
        ))
    output.sort(key=lambda item: (
        -authority_priors[item.version.authority], -item.score, -item.query_coverage,
        item.version.source_hash, item.span.ordinal,
    ))
    return output


def execute_hybrid_search(
    *, repository: Any, parameters: Any, candidate_budget: int, weights: Any,
    timeout_ms: int, semantic_source: Any | None, semantic_available: bool,
    authority_priors: dict[Any, float], contextual_projection_enabled: bool,
    approved_aliases: dict[str, tuple[str, ...]], identity: Identity, text: str,
    corpus_ids: frozenset[str], as_of: date, limit: int, semantic_enabled: bool | None,
    temporal_relevance: Callable[[date, date | None, date | None], float],
    diversify: Callable[..., list[RetrievedEvidence]], diversity_lambda: float,
    per_version_cap: int,
) -> list[RetrievedEvidence]:
    from korpus.application.retrieval_hybrid import execute_hybrid_search_impl
    return execute_hybrid_search_impl(
        repository=repository, parameters=parameters, candidate_budget=candidate_budget, weights=weights,
        timeout_ms=timeout_ms, semantic_source=semantic_source, semantic_available=semantic_available,
        authority_priors=authority_priors, contextual_projection_enabled=contextual_projection_enabled,
        approved_aliases=approved_aliases, identity=identity, text=text, corpus_ids=corpus_ids,
        as_of=as_of, limit=limit, semantic_enabled=semantic_enabled, temporal_relevance=temporal_relevance,
        diversify=diversify, diversity_lambda=diversity_lambda, per_version_cap=per_version_cap,
        semantic_candidates=_semantic_candidates, scoring_texts=_scoring_texts,
        materialize_evidence=_materialize_evidence, deadline_error=ExecutionDeadlineExceeded,
    )

