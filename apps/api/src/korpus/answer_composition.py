"""Composition root for the snapshot-bound answer retrieval runtime."""
from __future__ import annotations

from typing import Any

from korpus.application.answer_query import AnswerPolicy
from korpus.application.cache import CachedRetriever, EvidenceQueryCache
from korpus.application.calibration import CalibrationProfile
from korpus.application.corpus_snapshot import CorpusSnapshotReader
from korpus.application.retrieval import (
    BM25Parameters,
    HybridLexicalRetriever,
    RetrievalWeights,
)
from korpus.application.snapshot_retrieval import SnapshotBoundRetriever
from korpus.config import Settings
from korpus.infrastructure.repository import SqlRepository


def build_answer_runtime(
    repository: SqlRepository,
    snapshot_reader: CorpusSnapshotReader,
    cache: EvidenceQueryCache,
    semantic_source: Any | None,
    settings: Settings,
) -> tuple[AnswerPolicy, CachedRetriever]:
    """Build policy and retrieval from one calibrated configuration decision."""
    if settings.answer_policy_mode == "calibrated":
        profile = CalibrationProfile.load(
            settings.calibration_profile_path,  # type: ignore[arg-type]
            settings.calibration_profile_sha256,
        )
        answer_policy = AnswerPolicy(
            minimum_score=profile.minimum_score,
            minimum_query_coverage=profile.minimum_query_coverage,
            minimum_support_score=profile.minimum_support_score,
            calibration_id=profile.profile_id,
        )
        parameters = profile.bm25_parameters
        weights = profile.retrieval_weights
        candidate_budget = profile.retrieval_candidate_budget
        timeout_ms = profile.retrieval_timeout_ms
        diversity_lambda = profile.diversity_lambda
        per_version_cap = profile.per_version_cap
        configuration_id = profile.profile_id
        authority_priors = profile.authority_priors
    else:
        answer_policy = AnswerPolicy(
            minimum_score=settings.min_retrieval_score,
            minimum_query_coverage=settings.min_query_coverage,
            minimum_support_score=settings.min_support_score,
            calibration_id="development-unvalidated",
        )
        parameters = BM25Parameters()
        weights = RetrievalWeights(
            lexical=0.42 - settings.semantic_weight,
            semantic=settings.semantic_weight,
        )
        candidate_budget = settings.retrieval_candidate_budget
        timeout_ms = settings.retrieval_timeout_ms
        diversity_lambda = 0.82
        per_version_cap = 1
        configuration_id = "development-default-ranking-v5"
        authority_priors = None

    base = HybridLexicalRetriever(
        repository,
        parameters=parameters,
        candidate_budget=candidate_budget,
        weights=weights,
        diversity_lambda=diversity_lambda,
        per_version_cap=per_version_cap,
        timeout_ms=timeout_ms,
        semantic_source=semantic_source,
        authority_priors=authority_priors,
    )
    snapshot_bound = SnapshotBoundRetriever(snapshot_reader, base)
    retriever = CachedRetriever(snapshot_reader, snapshot_bound, cache, configuration_id)
    return answer_policy, retriever
