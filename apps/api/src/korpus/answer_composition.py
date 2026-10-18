"""Transport-independent composition of one calibrated answer pipeline."""

from __future__ import annotations

from typing import Any

from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.cache import EvidenceQueryCache
from korpus.application.calibration import CalibrationProfile
from korpus.application.composition import AnswerComposer
from korpus.application.pec_cache import PECCachedRetriever
from korpus.application.policy import PolicyEngine
from korpus.application.ports import Repository
from korpus.application.query_plan import QueryPlanner
from korpus.application.retrieval import BM25Parameters, HybridLexicalRetriever, RetrievalWeights
from korpus.config import Settings
from korpus.model_composition import build_answer_composer, build_query_planner
from korpus.pec_composition import build_predictive_controller
from korpus.tenancy_composition import build_egress_policy


def _retriever(
    repository: Repository,
    settings: Settings,
    semantic_source: Any | None,
    profile: CalibrationProfile | None,
) -> HybridLexicalRetriever:
    return HybridLexicalRetriever(
        repository,
        parameters=profile.bm25_parameters if profile else BM25Parameters(),
        candidate_budget=(
            profile.retrieval_candidate_budget if profile else settings.retrieval_candidate_budget
        ),
        weights=profile.retrieval_weights
        if profile
        else RetrievalWeights(
            lexical=0.42 - settings.semantic_weight, semantic=settings.semantic_weight
        ),
        diversity_lambda=profile.diversity_lambda if profile else 0.82,
        authority_relevance_floor=profile.authority_relevance_floor if profile else 0.80,
        per_version_cap=profile.per_version_cap if profile else 1,
        timeout_ms=profile.retrieval_timeout_ms if profile else settings.retrieval_timeout_ms,
        semantic_source=semantic_source,
        authority_priors=profile.authority_priors if profile else None,
        contextual_projection_enabled=settings.contextual_retrieval_enabled,
    )


def build_answer_service(
    repository: Repository,
    policy: PolicyEngine,
    settings: Settings,
    cache: EvidenceQueryCache,
    semantic_source: Any | None,
    query_planner: QueryPlanner | None = None,
    answer_composer: AnswerComposer | None = None,
) -> ExtractiveAnswerService:
    # One read binds answer thresholds and retrieval/cache identity to the same profile.
    profile = None
    if settings.answer_policy_mode == "calibrated":
        profile = CalibrationProfile.load(
            settings.calibration_profile_path,
            settings.calibration_profile_sha256,
        )
    answer_policy = AnswerPolicy(
        minimum_score=profile.minimum_score if profile else settings.min_retrieval_score,
        minimum_query_coverage=(
            profile.minimum_query_coverage if profile else settings.min_query_coverage
        ),
        minimum_support_score=(
            profile.minimum_support_score if profile else settings.min_support_score
        ),
        calibration_id=profile.profile_id if profile else "development-unvalidated",
    )
    retriever = PECCachedRetriever(
        repository,
        _retriever(repository, settings, semantic_source, profile),
        cache,
        profile.profile_id if profile else "development-default-ranking-v5",
    )
    return ExtractiveAnswerService(
        repository,
        retriever,
        policy,
        answer_policy,
        query_planner=query_planner if query_planner is not None else build_query_planner(settings),
        answer_composer=(
            answer_composer if answer_composer is not None else build_answer_composer(settings)
        ),
        egress_policy=build_egress_policy(settings),
        predictive_controller=build_predictive_controller(settings),
    )
