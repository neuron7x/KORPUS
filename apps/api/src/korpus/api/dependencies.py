from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.cache import CachedRetriever, EvidenceQueryCache
from korpus.application.calibration import CalibrationProfile
from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.ingestion_jobs import DurableIngestionCoordinator
from korpus.application.policy import PolicyEngine
from korpus.application.ports import ObjectStore
from korpus.application.query_plan import QueryPlanner
from korpus.application.resilience import AdmissionController
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.composition import build_ingestion_service
from korpus.config import Settings, get_settings
from korpus.infrastructure.anthropic_planner import AnthropicQueryPlanner
from korpus.infrastructure.ingestion_jobs import SqlIngestionJobQueue
from korpus.infrastructure.observability import Observability
from korpus.infrastructure.repository import SqlRepository
from korpus.security.corpus_governance import CorpusGovernanceProfile
from korpus.security.reviewers import ReviewerRegistry
from korpus.security.scanning import ClamdInstreamScanner, DisabledMalwareScanner
from korpus.security.source_authenticity import SourceTrustProfile

SettingsDependency = Annotated[Settings, Depends(get_settings)]


def get_policy(request: Request) -> PolicyEngine:
    policy: PolicyEngine = request.app.state.policy
    return policy


def get_repository(request: Request) -> SqlRepository:
    repository: SqlRepository = request.app.state.repository
    return repository


def get_object_store(request: Request) -> ObjectStore:
    object_store: ObjectStore = request.app.state.object_store
    return object_store


def get_quarantine_store(request: Request) -> ObjectStore:
    quarantine_store: ObjectStore = request.app.state.quarantine_store
    return quarantine_store


def get_ingestion_job_queue(request: Request) -> SqlIngestionJobQueue:
    ingestion_jobs: SqlIngestionJobQueue = request.app.state.ingestion_jobs
    return ingestion_jobs


def get_query_cache(request: Request) -> EvidenceQueryCache:
    query_cache: EvidenceQueryCache = request.app.state.query_cache
    return query_cache


def get_admission_controller(request: Request) -> AdmissionController:
    admission: AdmissionController = request.app.state.admission
    return admission


def get_ingestion_admission_controller(request: Request) -> AdmissionController:
    ingestion_admission: AdmissionController = request.app.state.ingestion_admission
    return ingestion_admission


def get_observability(request: Request) -> Observability:
    observability: Observability = request.app.state.observability
    return observability


def get_semantic_source(request: Request) -> Any | None:
    return request.app.state.semantic_source


def get_ingestion_service(
    repository: Annotated[SqlRepository, Depends(get_repository)],
    object_store: Annotated[ObjectStore, Depends(get_object_store)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
    settings: SettingsDependency,
) -> IngestionService:
    return build_ingestion_service(
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
            ocr_total_timeout_seconds=settings.ocr_total_timeout_seconds,
            parser_sandbox_enabled=settings.parser_sandbox_enabled,
            parser_timeout_seconds=settings.parser_timeout_seconds,
            parser_memory_limit_mb=settings.parser_memory_limit_mb,
            parser_output_limit_bytes=settings.parser_output_limit_bytes,
        ),
        review_separation_required=settings.review_separation_required,
        source_trust_profile=(
            SourceTrustProfile.load(
                settings.source_trust_profile_path, settings.source_trust_profile_sha256
            )
            if settings.source_trust_profile_path is not None
            else None
        ),
        require_source_signature=settings.require_source_signatures,
        reviewer_registry=(
            ReviewerRegistry.load(
                settings.reviewer_registry_path, settings.reviewer_registry_sha256
            )
            if settings.reviewer_registry_path is not None
            else None
        ),
        require_reviewer_credentials=(
            settings.environment in {"production", "controlled", "isolated"}
        ),
        corpus_governance=(
            CorpusGovernanceProfile.load(
                settings.corpus_governance_profile_path, settings.corpus_governance_profile_sha256
            )
            if settings.corpus_governance_profile_path is not None
            else None
        ),
        require_corpus_governance=settings.environment in {"production", "controlled", "isolated"},
        malware_scanner=(
            ClamdInstreamScanner(
                settings.clamd_host,
                settings.clamd_port,
                timeout_seconds=settings.malware_scan_timeout_seconds,
                max_bytes=settings.max_upload_bytes,
            )
            if settings.malware_scan_mode == "clamd"
            else DisabledMalwareScanner()
        ),
    )


def get_durable_ingestion_coordinator(
    queue: Annotated[SqlIngestionJobQueue, Depends(get_ingestion_job_queue)],
    quarantine_store: Annotated[ObjectStore, Depends(get_quarantine_store)],
    repository: Annotated[SqlRepository, Depends(get_repository)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
    settings: SettingsDependency,
) -> DurableIngestionCoordinator:
    return DurableIngestionCoordinator(
        queue,
        quarantine_store,
        repository,
        policy,
        max_attempts=settings.ingestion_job_max_attempts,
    )


def get_answer_service(
    repository: Annotated[SqlRepository, Depends(get_repository)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
    settings: SettingsDependency,
    cache: Annotated[EvidenceQueryCache, Depends(get_query_cache)],
    semantic_source: Annotated[Any | None, Depends(get_semantic_source)],
) -> ExtractiveAnswerService:
    if settings.answer_policy_mode == "calibrated":
        profile = CalibrationProfile.load(
            # calibrated mode is rejected at settings validation unless the path is set
            settings.calibration_profile_path,  # type: ignore[arg-type]
            settings.calibration_profile_sha256,
        )
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
        profile = CalibrationProfile.load(
            # calibrated mode is rejected at settings validation unless the path is set
            settings.calibration_profile_path,  # type: ignore[arg-type]
            settings.calibration_profile_sha256,
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
        from korpus.application.retrieval import BM25Parameters, RetrievalWeights

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
    retriever = CachedRetriever(repository, base, cache, configuration_id)
    return ExtractiveAnswerService(
        repository, retriever, policy, answer_policy, query_planner=build_query_planner(settings)
    )


def build_query_planner(settings: Settings) -> QueryPlanner | None:
    """The reformulator, when an operator has switched it on and supplied a key.

    Public because the drills need the same seam the application uses. A chaos case that
    reached past this to attach a planner to one service instance would be testing a
    service the next request does not use.

    Returning None is the whole of the "off" path: `build_plan` treats a missing planner
    and a broken one identically, so nothing downstream branches on this.
    """
    if not settings.query_planner_enabled or not settings.query_planner_api_key:
        return None
    return AnthropicQueryPlanner(
        settings.query_planner_api_key,
        model=settings.query_planner_model,
        base_url=settings.query_planner_base_url,
        timeout_seconds=settings.query_planner_timeout_seconds,
    )
