from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.calibration import CalibrationProfile
from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.policy import PolicyEngine
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.config import Settings, get_settings
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.repository import SqlRepository

SettingsDependency = Annotated[Settings, Depends(get_settings)]


def get_policy(request: Request) -> PolicyEngine:
    return request.app.state.policy


def get_repository(request: Request) -> SqlRepository:
    return request.app.state.repository


def get_object_store(request: Request) -> LocalObjectStore:
    return request.app.state.object_store


def get_ingestion_service(
    repository: Annotated[SqlRepository, Depends(get_repository)],
    object_store: Annotated[LocalObjectStore, Depends(get_object_store)],
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
    return ExtractiveAnswerService(
        repository,
        HybridLexicalRetriever(
            repository, candidate_budget=settings.retrieval_candidate_budget
        ),
        policy,
        answer_policy,
    )
