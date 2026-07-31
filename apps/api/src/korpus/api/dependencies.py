from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.policy import PolicyEngine
from korpus.application.retrieval import LexicalRetriever
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
        ExtractionSettings(ocr_enabled=settings.ocr_enabled, ocr_languages=settings.ocr_languages),
    )


def get_answer_service(
    repository: Annotated[SqlRepository, Depends(get_repository)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
    settings: SettingsDependency,
) -> ExtractiveAnswerService:
    return ExtractiveAnswerService(
        repository,
        LexicalRetriever(repository),
        policy,
        AnswerPolicy(
            minimum_score=settings.min_retrieval_score,
            minimum_query_coverage=settings.min_query_coverage,
        ),
    )
