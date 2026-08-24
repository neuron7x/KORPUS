from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from korpus.api.dependencies import (
    get_durable_ingestion_coordinator,
    get_ingestion_admission_controller,
    get_ingestion_job_queue,
    get_ingestion_service,
    get_observability,
    get_policy,
    get_repository,
)
from korpus.api.overload_http import overload_http_exception
from korpus.application.ingestion import IngestionService
from korpus.application.ingestion_jobs import DurableIngestionCoordinator
from korpus.application.policy import AuthorizationError, PolicyEngine
from korpus.application.resilience import AdmissionController, OverloadedError
from korpus.config import Settings, get_settings
from korpus.domain.models import (
    DocumentCreate,
    DocumentRecord,
    Identity,
    IngestionJobRecord,
    IngestResult,
    VersionCreate,
)
from korpus.infrastructure.ingestion_jobs import SqlIngestionJobQueue
from korpus.infrastructure.observability import Observability
from korpus.infrastructure.repository import SqlRepository
from korpus.security.auth import get_identity

router = APIRouter()
IdentityDependency = Annotated[Identity, Depends(get_identity)]


@dataclass(frozen=True)
class SpoolUpload:
    path: Path
    source_hash: str
    size: int


async def _spool_upload_limited(file: UploadFile, maximum_bytes: int) -> SpoolUpload:
    suffix = Path(file.filename or "upload.bin").suffix[:16]
    descriptor, name = tempfile.mkstemp(prefix="korpus-upload-", suffix=suffix)
    hasher = hashlib.sha256()
    total = 0
    try:
        try:
            with os.fdopen(descriptor, "wb") as handle:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > maximum_bytes:
                        raise ValueError("upload exceeds configured size limit")
                    hasher.update(chunk)
                    handle.write(chunk)
                if total == 0:
                    raise ValueError("empty document")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            # The spool lives on a small tmpfs; a burst of concurrent uploads fills it and
            # the write raises ENOSPC. That is a capacity limit, not a bad request — a 503
            # so the client retries later, never a 500 that reads as the system breaking.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="upload staging is full; retry shortly",
                headers={"Retry-After": "2"},
            ) from exc
        os.chmod(name, 0o600)
        return SpoolUpload(Path(name), hasher.hexdigest(), total)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    finally:
        await file.close()


async def _run_bounded_ingestion[T](
    admission: AdmissionController,
    observability: Observability,
    operation: Callable[[], T],
    subject: str | None = None,
) -> T:
    def execute() -> T:
        try:
            with admission.acquire(subject):
                observability.ingestion_admission_active.set(admission.snapshot().active)
                return operation()
        finally:
            observability.ingestion_admission_active.set(admission.snapshot().active)

    try:
        return await run_in_threadpool(execute)
    except OverloadedError as exc:
        raise overload_http_exception(exc) from exc


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


@router.post(
    "/v1/documents/ingest", response_model=IngestResult, status_code=status.HTTP_201_CREATED
)
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
    if settings.ingestion_mode != "synchronous":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="use durable ingestion jobs"
        )
    try:
        document = DocumentCreate.model_validate(json.loads(document_json))
        version = VersionCreate.model_validate(json.loads(version_json))
        filename = file.filename or "upload.bin"
        mime_type = file.content_type or "application/octet-stream"
        spool = await _spool_upload_limited(file, settings.max_upload_bytes)
        try:
            return await _run_bounded_ingestion(
                admission,
                observability,
                subject=identity.subject,
                operation=lambda: service.ingest_path(
                    identity,
                    document,
                    version,
                    filename=filename,
                    mime_type=mime_type,
                    path=spool.path,
                    source_hash=spool.source_hash,
                ),
            )
        finally:
            spool.path.unlink(missing_ok=True)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


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
    if settings.ingestion_mode != "synchronous":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="use durable ingestion jobs"
        )
    try:
        version = VersionCreate.model_validate(json.loads(version_json))
        filename = file.filename or "upload.bin"
        mime_type = file.content_type or "application/octet-stream"
        spool = await _spool_upload_limited(file, settings.max_upload_bytes)
        try:
            return await _run_bounded_ingestion(
                admission,
                observability,
                subject=identity.subject,
                operation=lambda: service.ingest_version_path(
                    identity,
                    document_id,
                    version,
                    filename=filename,
                    mime_type=mime_type,
                    path=spool.path,
                    source_hash=spool.source_hash,
                ),
            )
        finally:
            spool.path.unlink(missing_ok=True)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post(
    "/v1/ingestion-jobs/documents",
    response_model=IngestionJobRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_document_ingestion_job(
    identity: IdentityDependency,
    coordinator: Annotated[DurableIngestionCoordinator, Depends(get_durable_ingestion_coordinator)],
    settings: Annotated[Settings, Depends(get_settings)],
    admission: Annotated[AdmissionController, Depends(get_ingestion_admission_controller)],
    observability: Annotated[Observability, Depends(get_observability)],
    document_json: Annotated[str, Form()],
    version_json: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> IngestionJobRecord:
    if settings.ingestion_mode != "durable_async":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="durable ingestion is disabled"
        )
    try:
        document = DocumentCreate.model_validate(json.loads(document_json))
        version = VersionCreate.model_validate(json.loads(version_json))
        filename = file.filename or "upload.bin"
        mime_type = file.content_type or "application/octet-stream"
        spool = await _spool_upload_limited(file, settings.max_upload_bytes)
        try:
            return await _run_bounded_ingestion(
                admission,
                observability,
                subject=identity.subject,
                operation=lambda: coordinator.submit_document(
                    identity,
                    document,
                    version,
                    filename=filename,
                    mime_type=mime_type,
                    path=spool.path,
                    source_hash=spool.source_hash,
                ),
            )
        finally:
            spool.path.unlink(missing_ok=True)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post(
    "/v1/documents/{document_id}/ingestion-jobs",
    response_model=IngestionJobRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_version_ingestion_job(
    document_id: UUID,
    identity: IdentityDependency,
    coordinator: Annotated[DurableIngestionCoordinator, Depends(get_durable_ingestion_coordinator)],
    settings: Annotated[Settings, Depends(get_settings)],
    admission: Annotated[AdmissionController, Depends(get_ingestion_admission_controller)],
    observability: Annotated[Observability, Depends(get_observability)],
    version_json: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> IngestionJobRecord:
    if settings.ingestion_mode != "durable_async":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="durable ingestion is disabled"
        )
    try:
        version = VersionCreate.model_validate(json.loads(version_json))
        filename = file.filename or "upload.bin"
        mime_type = file.content_type or "application/octet-stream"
        spool = await _spool_upload_limited(file, settings.max_upload_bytes)
        try:
            return await _run_bounded_ingestion(
                admission,
                observability,
                subject=identity.subject,
                operation=lambda: coordinator.submit_version(
                    identity,
                    document_id,
                    version,
                    filename=filename,
                    mime_type=mime_type,
                    path=spool.path,
                    source_hash=spool.source_hash,
                ),
            )
        finally:
            spool.path.unlink(missing_ok=True)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get("/v1/ingestion-jobs/{job_id}", response_model=IngestionJobRecord)
def get_ingestion_job(
    job_id: UUID,
    identity: IdentityDependency,
    queue: Annotated[SqlIngestionJobQueue, Depends(get_ingestion_job_queue)],
) -> IngestionJobRecord:
    job = queue.get(identity, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ingestion job not found")
    return job
