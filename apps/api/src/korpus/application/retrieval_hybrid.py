"""Hybrid retrieval execution with bounded candidate and evidence budgets."""
from __future__ import annotations

import time

from korpus.application.retrieval_math import score_candidates


def _initial_candidates(repository, contextual_enabled, approved_aliases, identity, corpus_ids, as_of, text, budget):
    contextual = getattr(repository, "search_contextual_retrievable_spans", None)
    if contextual_enabled and callable(contextual):
        return contextual(identity, corpus_ids, as_of, text, budget, approved_aliases=approved_aliases)
    return repository.search_retrievable_spans(identity, corpus_ids, as_of, text, budget)


def execute_hybrid_search_impl(
    *, repository, parameters, candidate_budget, weights, timeout_ms, semantic_source,
    semantic_available, authority_priors, contextual_projection_enabled, approved_aliases,
    identity, text, corpus_ids, as_of, limit, semantic_enabled, temporal_relevance,
    diversify, diversity_lambda, per_version_cap, semantic_candidates, scoring_texts,
    materialize_evidence, deadline_error,
):
    started = time.monotonic()
    candidates = _initial_candidates(
        repository, contextual_projection_enabled, approved_aliases,
        identity, corpus_ids, as_of, text, candidate_budget,
    )
    semantic_by_span: dict[str, float] = {}
    use_semantic = semantic_available if semantic_enabled is None else semantic_enabled
    if use_semantic:
        candidates, semantic_by_span = semantic_candidates(
            repository, semantic_source, candidates, identity, text, corpus_ids, as_of, candidate_budget
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
        temporal_scores=[temporal_relevance(as_of, version.publication_date, version.effective_from) for _, _, version in candidates],
        weights=weights,
    )
    return diversify(
        materialize_evidence(candidates, components, authority_priors),
        limit=limit,
        diversity_lambda=diversity_lambda,
        per_version_cap=per_version_cap,
        authority_priors=authority_priors,
    )
