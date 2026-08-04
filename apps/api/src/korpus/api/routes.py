from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse

from korpus.api.dependencies import (
    get_admission_controller,
    get_answer_service,
    get_durable_ingestion_coordinator,
    get_ingestion_admission_controller,
    get_ingestion_job_queue,
    get_ingestion_service,
    get_object_store,
    get_observability,
    get_policy,
    get_repository,
)
from korpus.application.answer_query import ExtractiveAnswerService
from korpus.application.ingestion import IngestionService
from korpus.application.ingestion_jobs import DurableIngestionCoordinator
from korpus.application.policy import (
    AuthorizationError,
    PolicyEngine,
    UnauthorizedCorporaError,
)
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
    IngestionJobRecord,
    IngestResult,
    QueryRequest,
    ReviewTransition,
    VersionCreate,
)
from korpus.infrastructure.ingestion_jobs import SqlIngestionJobQueue
from korpus.infrastructure.observability import Observability
from korpus.infrastructure.repository import ConcurrentWriteError, SqlRepository
from korpus.security.auth import get_identity
from korpus.security.browser_oidc import BrowserSessionError

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
    payload = {
        **snapshot,
        "object_store": object_store_ok,
        "schema_current": schema_ok,
        "ready": is_ready,
    }
    if not is_ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=payload)
    # readiness_snapshot always stores an int under this key (repository.readiness_snapshot)
    audit_head = int(snapshot["audit_head_sequence"])  # type: ignore[call-overload]
    return {"status": "ready", "audit_head": audit_head}


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


def _safe_return_path(value: str) -> str:
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value[:1024]


@router.get("/v1/auth/login", include_in_schema=False)
def browser_login(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    return_to: Annotated[str, Query(max_length=1024)] = "/",
) -> Response:
    if not settings.browser_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="browser authentication disabled"
        )
    client = getattr(request.app.state, "browser_oidc_client", None)
    codec = getattr(request.app.state, "browser_session_codec", None)
    if client is None or codec is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="browser authentication unavailable",
        )
    flow = client.new_flow()
    flow_cookie = codec.seal(
        "flow",
        {
            "state": flow["state"],
            "nonce": flow["nonce"],
            "code_verifier": flow["code_verifier"],
            "return_to": _safe_return_path(return_to),
        },
        ttl_seconds=settings.browser_flow_ttl_seconds,
    )
    response = RedirectResponse(client.authorization_url(flow), status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        settings.browser_flow_cookie,
        flow_cookie,
        max_age=settings.browser_flow_ttl_seconds,
        httponly=True,
        secure=settings.browser_cookie_secure,
        samesite="lax",
        path="/v1/auth",
    )
    return response


@router.get("/v1/auth/callback", include_in_schema=False)
def browser_callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str, Query(min_length=1, max_length=4096)],
    state_value: Annotated[str, Query(alias="state", min_length=16, max_length=512)],
) -> Response:
    if not settings.browser_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="browser authentication disabled"
        )
    flow_cookie = request.cookies.get(settings.browser_flow_cookie)
    client = getattr(request.app.state, "browser_oidc_client", None)
    codec = getattr(request.app.state, "browser_session_codec", None)
    verifier = getattr(request.app.state, "oidc_verifier", None)
    if not flow_cookie or client is None or codec is None or verifier is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="OIDC flow state unavailable"
        )
    try:
        flow = codec.open(flow_cookie, expected_kind="flow")
        expected_state = flow.get("state")
        if not isinstance(expected_state, str) or not hmac.compare_digest(
            expected_state, state_value
        ):
            raise BrowserSessionError("OIDC state mismatch")
        tokens = client.exchange(code, str(flow.get("code_verifier", "")))
        id_claims = verifier.verify(
            tokens.id_token,
            audience=settings.oidc_client_id,
            expected_nonce=str(flow.get("nonce", "")),
        )
        access_claims = verifier.verify(tokens.access_token)
        if str(id_claims.get("sub")) != str(access_claims.get("sub")):
            raise BrowserSessionError("OIDC token subjects differ")
        csrf = __import__("secrets").token_urlsafe(32)
        ttl = min(settings.browser_session_ttl_seconds, tokens.expires_in)
        session_cookie = codec.seal(
            "session",
            {"access_token": tokens.access_token, "csrf": csrf},
            ttl_seconds=ttl,
        )
    except (BrowserSessionError, ValueError, jwt.PyJWTError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="OIDC callback validation failed"
        ) from exc
    response = RedirectResponse(
        _safe_return_path(str(flow.get("return_to", "/"))),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.delete_cookie(settings.browser_flow_cookie, path="/v1/auth")
    response.set_cookie(
        settings.browser_session_cookie,
        session_cookie,
        max_age=ttl,
        httponly=True,
        secure=settings.browser_cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        settings.browser_csrf_cookie,
        csrf,
        max_age=ttl,
        httponly=False,
        secure=settings.browser_cookie_secure,
        samesite="strict",
        path="/",
    )
    return response


@router.post("/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
def browser_logout(settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.browser_session_cookie, path="/")
    response.delete_cookie(settings.browser_csrf_cookie, path="/")
    response.delete_cookie(settings.browser_flow_cookie, path="/v1/auth")
    return response


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
                lambda: service.ingest_path(
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
                lambda: service.ingest_version_path(
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
                lambda: coordinator.submit_document(
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
                lambda: coordinator.submit_version(
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


@router.post("/v1/document-versions/{version_id}/review", response_model=DocumentVersionRecord)
def review_version(
    version_id: UUID,
    transition: ReviewTransition,
    identity: IdentityDependency,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> DocumentVersionRecord:
    try:
        return service.transition(identity, version_id, transition)
    except PermissionError as exc:
        # AuthorizationError is one of these; so is an approver reaching for a tier
        # above their own clearance, which is a refusal rather than a server fault.
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
    except UnauthorizedCorporaError as exc:
        # Typed, and in the order the reader asked: a refusal that does not say which
        # corpus was refused cannot be acted on by the reader or by an operator.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "reason": exc.reason,
                "denied_corpora": exc.denied,
                "requested_corpora": exc.requested,
            },
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
