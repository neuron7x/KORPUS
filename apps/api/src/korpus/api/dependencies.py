from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.cache import CachedRetriever, EvidenceQueryCache
from korpus.application.calibration import CalibrationProfile
from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.policy import PolicyEngine
from korpus.application.resilience import AdmissionController
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.config import Settings, get_settings
from korpus.application.ports import ObjectStore
from korpus.infrastructure.observability import Observability
from korpus.infrastructure.repository import SqlRepository

SettingsDependency = Annotated[Settings, Depends(get_settings)]


def get_policy(request: Request) -> PolicyEngine:
    return request.app.state.policy


def get_repository(request: Request) -> SqlRepository:
    return request.app.state.repository


def get_object_store(request: Request) -> ObjectStore:
    return request.app.state.object_store


def get_query_cache(request: Request) -> EvidenceQueryCache:
    return request.app.state.query_cache


def get_admission_controller(request: Request) -> AdmissionController:
    return request.app.state.admission


def get_ingestion_admission_controller(request: Request) -> AdmissionController:
    return request.app.state.ingestion_admission


def get_observability(request: Request) -> Observability:
    return request.app.state.observability


def get_semantic_source(request: Request) -> Any | None:
    return request.app.state.semantic_source


def get_ingestion_service(
    repository: Annotated[SqlRepository, Depends(get_repository)],
    object_store: Annotated[ObjectStore, Depends(get_object_store)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
    settings: SettingsDependency,
) -> IngestionService:
    return IngestionService(
        repository,
        object_store,
        policy,
        ExtractionSettings(
            ocr_enabled=settings.ocr_enabled,
            ocr_languages=settings.ocr_languages,
            max_pdf_pages=settings.max_pdf_pages,
            max_spans_per_document=settings.max_spans_per_document,
            max_chunk_chars=settings.max_chunk_chars,
            chunk_overlap_chars=settings.chunk_overlap_chars,
        ),
        review_separation_required=settings.review_separation_required,
    )


def get_answer_service(
    repository: Annotated[SqlRepository, Depends(get_repository)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
    settings: SettingsDependency,
    cache: Annotated[EvidenceQueryCache, Depends(get_query_cache)],
    semantic_source: Any | None = Depends(get_semantic_source),
) -> ExtractiveAnswerService:
    if settings.answer_policy_mode == "calibrated":
        profile = CalibrationProfile.load(settings.calibration_profile_path)  # type: ignore[arg-type]
        answer_policy = AnswerPolicy(
            minimum_score=profile.minimum_score,
            minimum_query_coverage=profile.minimum_query_coverage,
            minimum_support_score=profile.minimum_support_score,
            calibration_id=profile.profile_id,
        )
    else:
        answer_policy = AnswerPolicy(
            minimum_score=settings.min_retrieval_score,
            minimum_query_coverage=settings.min_query_coverage,
            minimum_support_score=settings.min_support_score,
            calibration_id="development-unvalidated",
        )
    if settings.answer_policy_mode == "calibrated":
        profile = CalibrationProfile.load(settings.calibration_profile_path)  # type: ignore[arg-type]
        parameters = profile.bm25_parameters
        weights = profile.retrieval_weights
        candidate_budget = profile.retrieval_candidate_budget
        timeout_ms = profile.retrieval_timeout_ms
        diversity_lambda = profile.diversity_lambda
        per_version_cap = profile.per_version_cap
        configuration_id = profile.profile_id
    else:
        from korpus.application.retrieval import BM25Parameters, RetrievalWeights

        parameters = BM25Parameters()
        weights = RetrievalWeights(
            lexical=0.42 - settings.semantic_weight,
            semantic=settings.semantic_weight,
        )
        candidate_budget = settings.retrieval_candidate_budget
        timeout_ms = settings.retrieval_timeout_ms
        diversity_lambda = 0.82
        per_version_cap = 2
        configuration_id = "development-default-ranking-v3"
    base = HybridLexicalRetriever(
        repository,
        parameters=parameters,
        candidate_budget=candidate_budget,
        weights=weights,
        diversity_lambda=diversity_lambda,
        per_version_cap=per_version_cap,
        timeout_ms=timeout_ms,
        semantic_source=semantic_source,
    )
    retriever = CachedRetriever(repository, base, cache, configuration_id)
    return ExtractiveAnswerService(repository, retriever, policy, answer_policy)
