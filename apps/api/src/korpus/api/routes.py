from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from korpus.api.dependencies import (
    get_answer_service,
    get_ingestion_service,
    get_policy,
    get_repository,
)
from korpus.application.answer_query import ExtractiveAnswerService
from korpus.application.ingestion import IngestionService
from korpus.application.policy import AuthorizationError, PolicyEngine
from korpus.domain.models import (
    Answer,
    AuditVerification,
    DocumentCreate,
    DocumentRecord,
    Identity,
    IngestResult,
    QueryRequest,
    ReviewTransition,
    VersionCreate,
    DocumentVersionRecord,
)
from korpus.infrastructure.repository import SqlRepository
from korpus.security.auth import get_identity

router = APIRouter()
IdentityDependency = Annotated[Identity, Depends(get_identity)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(repository: Annotated[SqlRepository, Depends(get_repository)]) -> dict[str, str]:
    return {"status": "ready", "corpus_release": repository.corpus_release_id()}


@router.get("/v1/auth/me", response_model=Identity)
def me(identity: IdentityDependency) -> Identity:
    return identity


@router.get("/v1/documents", response_model=list[DocumentRecord])
def list_documents(
    identity: IdentityDependency,
    repository: Annotated[SqlRepository, Depends(get_repository)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
) -> list[DocumentRecord]:
    try:
        policy.require(identity, "document:list")
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return repository.list_documents(identity)


@router.post("/v1/documents/ingest", response_model=IngestResult, status_code=status.HTTP_201_CREATED)
async def ingest_document(
    identity: IdentityDependency,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
    document_json: Annotated[str, Form()],
    version_json: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> IngestResult:
    try:
        document = DocumentCreate.model_validate(json.loads(document_json))
        version = VersionCreate.model_validate(json.loads(version_json))
        content = await file.read()
        return service.ingest(
            identity,
            document,
            version,
            filename=file.filename or "upload.bin",
            mime_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/v1/documents/{document_id}/versions/ingest",
    response_model=IngestResult,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_document_version(
    document_id: UUID,
    identity: IdentityDependency,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
    version_json: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> IngestResult:
    try:
        version = VersionCreate.model_validate(json.loads(version_json))
        content = await file.read()
        return service.ingest_version(
            identity,
            document_id,
            version,
            filename=file.filename or "upload.bin",
            mime_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/v1/document-versions/{version_id}/review")
def review_version(
    version_id: UUID,
    transition: ReviewTransition,
    identity: IdentityDependency,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> DocumentVersionRecord:
    try:
        return service.transition(identity, version_id, transition)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/v1/answers", response_model=Answer)
def create_answer(
    query: QueryRequest,
    identity: IdentityDependency,
    service: Annotated[ExtractiveAnswerService, Depends(get_answer_service)],
) -> Answer:
    try:
        return service.execute(identity, query)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/v1/audit/verify", response_model=AuditVerification)
def verify_audit(
    identity: IdentityDependency,
    repository: Annotated[SqlRepository, Depends(get_repository)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
) -> AuditVerification:
    try:
        policy.require(identity, "audit:verify")
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return repository.verify_audit()
