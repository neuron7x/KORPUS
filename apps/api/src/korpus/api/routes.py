from __future__ import annotations

import hmac
import json
from typing import Annotated, Callable, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Response, UploadFile, status
from starlette.concurrency import run_in_threadpool

from korpus.api.dependencies import (
    get_admission_controller,
    get_answer_service,
    get_ingestion_admission_controller,
    get_ingestion_service,
    get_object_store,
    get_observability,
    get_policy,
    get_repository,
)
from korpus.application.answer_query import ExtractiveAnswerService
from korpus.application.ingestion import IngestionService
from korpus.application.policy import AuthorizationError, PolicyEngine
from korpus.application.ports import ObjectStore
from korpus.application.resilience import AdmissionController, OverloadedError
from korpus.config import Settings, get_settings
from korpus.domain.models import (
    Answer,
    AuditVerification,
    DocumentCreate,
    DocumentRecord,
    DocumentVersionRecord,
    Identity,
    IngestResult,
    QueryRequest,
    ReviewTransition,
    VersionCreate,
)
from korpus.infrastructure.observability import Observability
from korpus.infrastructure.repository import ConcurrentWriteError, SqlRepository
from korpus.security.auth import get_identity

router = APIRouter()
IdentityDependency = Annotated[Identity, Depends(get_identity)]
T = TypeVar("T")


async def _read_upload_limited(file: UploadFile, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum_bytes:
            raise ValueError("upload exceeds configured size limit")
        chunks.append(chunk)
    return b"".join(chunks)


async def _run_bounded_ingestion(
    admission: AdmissionController,
    observability: Observability,
    operation: Callable[[], T],
) -> T:
    def execute() -> T:
        try:
            with admission.acquire():
                observability.ingestion_admission_active.set(admission.snapshot().active)
                return operation()
        finally:
            observability.ingestion_admission_active.set(admission.snapshot().active)

    try:
        return await run_in_threadpool(execute)
    except OverloadedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ingestion capacity exhausted",
            headers={"Retry-After": "1"},
        ) from exc


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(
    repository: Annotated[SqlRepository, Depends(get_repository)],
    object_store: Annotated[ObjectStore, Depends(get_object_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    try:
        snapshot = repository.readiness_snapshot(
            max_pending_events=settings.audit_max_pending_events,
            max_pending_age_seconds=settings.audit_max_pending_age_seconds,
        )
        object_store_ok = object_store.healthcheck()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"ready": False, "reason": type(exc).__name__},
        ) from exc
    schema_ok = (
        snapshot["schema_revision"] == snapshot["expected_schema_revision"]
        if settings.schema_mode == "migrations"
        else True
    )
    is_ready = bool(snapshot["ready"] and object_store_ok and schema_ok)
    payload = {**snapshot, "object_store": object_store_ok, "schema_current": schema_ok, "ready": is_ready}
    if not is_ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=payload)
    return {"status": "ready", "audit_head": int(snapshot["audit_head_sequence"])}


@router.get("/metrics", include_in_schema=False)
def metrics(
    settings: Annotated[Settings, Depends(get_settings)],
    observability: Annotated[Observability, Depends(get_observability)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="metrics disabled")
    expected = settings.resolved_metrics_token
    if expected is not None:
        supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="metrics authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return Response(observability.export_prometheus(), media_type="text/plain; version=0.0.4")


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
    settings: Annotated[Settings, Depends(get_settings)],
    admission: Annotated[AdmissionController, Depends(get_ingestion_admission_controller)],
    observability: Annotated[Observability, Depends(get_observability)],
    document_json: Annotated[str, Form()],
    version_json: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> IngestResult:
    try:
        document = DocumentCreate.model_validate(json.loads(document_json))
        version = VersionCreate.model_validate(json.loads(version_json))
        content = await _read_upload_limited(file, settings.max_upload_bytes)
        return await _run_bounded_ingestion(
            admission,
            observability,
            lambda: service.ingest(
                identity,
                document,
                version,
                filename=file.filename or "upload.bin",
                mime_type=file.content_type or "application/octet-stream",
                content=content,
            ),
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
    settings: Annotated[Settings, Depends(get_settings)],
    admission: Annotated[AdmissionController, Depends(get_ingestion_admission_controller)],
    observability: Annotated[Observability, Depends(get_observability)],
    version_json: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> IngestResult:
    try:
        version = VersionCreate.model_validate(json.loads(version_json))
        content = await _read_upload_limited(file, settings.max_upload_bytes)
        return await _run_bounded_ingestion(
            admission,
            observability,
            lambda: service.ingest_version(
                identity,
                document_id,
                version,
                filename=file.filename or "upload.bin",
                mime_type=file.content_type or "application/octet-stream",
                content=content,
            ),
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/v1/document-versions/{version_id}/review", response_model=DocumentVersionRecord)
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
    except ConcurrentWriteError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/v1/answers", response_model=Answer)
def create_answer(
    query: QueryRequest,
    identity: IdentityDependency,
    service: Annotated[ExtractiveAnswerService, Depends(get_answer_service)],
    admission: Annotated[AdmissionController, Depends(get_admission_controller)],
    observability: Annotated[Observability, Depends(get_observability)],
) -> Answer:
    try:
        try:
            with admission.acquire():
                observability.answer_admission_active.set(admission.snapshot().active)
                with observability.measure_retrieval():
                    answer = service.execute(identity, query)
        finally:
            observability.answer_admission_active.set(admission.snapshot().active)
        from korpus.application.risk import classify_query_risk

        observability.observe_answer(
            answer.status.value, answer.decision_reason, classify_query_risk(query.text).value
        )
        return answer
    except OverloadedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="answer capacity exhausted",
            headers={"Retry-After": "1"},
        ) from exc
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
