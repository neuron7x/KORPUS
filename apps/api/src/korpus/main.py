from __future__ import annotations

import asyncio
import os
import re
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from korpus import __version__
from korpus.api.routes import router
from korpus.api.routes_admin import admin_router
from korpus.api.routes_billing import billing_router
from korpus.api.routes_tenancy import tenancy_router
from korpus.application.cache import EvidenceQueryCache
from korpus.application.policy import PolicyEngine
from korpus.application.resilience import AdmissionController
from korpus.application.trace import reset_trace_id, set_trace_id
from korpus.config import Settings, get_settings, unknown_settings_variables
from korpus.infrastructure.ingestion_jobs import SqlIngestionJobQueue
from korpus.infrastructure.observability import Observability
from korpus.infrastructure.runtime import (
    create_object_store,
    create_quarantine_store,
    create_repository,
)
from korpus.infrastructure.semantic import HttpEmbeddingProvider, PgVectorSemanticIndex
from korpus.security.browser_oidc import BrowserOIDCClient, BrowserSessionCodec, BrowserSessionError
from korpus.security.corpus_governance import CorpusGovernanceProfile
from korpus.security.oidc import OIDCVerifier
from korpus.tenancy_composition import install_tenancy

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

def create_app(settings: Settings | None = None) -> FastAPI:
    selected = settings or get_settings()

    # A misspelled KORPUS_* variable is dropped in silence by pydantic-settings, so
    # `KORPUS_REQUIRE_SOURCE_SIGNATURE=true` — singular, where the field is
    # `require_source_signatures` — starts a process with the control off and nothing
    # reported. The deployment reads correct in review. Refused at startup rather than
    # warned about: a control an operator believes is on and is not is worse than a
    # process that does not start.
    unknown = unknown_settings_variables(os.environ)
    if unknown:
        raise ValueError(
            "unrecognised KORPUS_* environment variables — a typo here silently leaves "
            f"a setting at its default: {unknown}"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        policy = PolicyEngine()
        repository = create_repository(selected, policy)
        repository.initialize(create_schema=selected.schema_mode == "auto")
        object_store = create_object_store(selected)
        quarantine_store = create_quarantine_store(selected)
        ingestion_jobs = SqlIngestionJobQueue(repository.engine)
        observability = Observability(
            service_name=selected.service_name, otlp_endpoint=selected.otlp_endpoint
        )
        corpus_governance = (
            CorpusGovernanceProfile.load(
                selected.corpus_governance_profile_path, selected.corpus_governance_profile_sha256
            )
            if selected.corpus_governance_profile_path is not None
            else None
        )
        semantic_source = (
            PgVectorSemanticIndex(
                repository.engine,
                HttpEmbeddingProvider(
                    endpoint=selected.embedding_endpoint or "",
                    model_id=selected.embedding_model_id or "",
                    dimensions=selected.embedding_dimensions,
                    token=selected.resolved_embedding_token,
                    timeout_seconds=selected.embedding_timeout_seconds,
                    max_attempts=selected.embedding_max_attempts,
                    max_response_bytes=selected.embedding_max_response_bytes,
                ),
                corpus_governance=corpus_governance,
            )
            if selected.semantic_retrieval_enabled
            else None
        )
        oidc_verifier = (
            OIDCVerifier(
                jwks_url=selected.oidc_jwks_url or "",
                issuer=selected.jwt_issuer,
                audience=selected.jwt_audience,
                algorithms=selected.oidc_algorithm_list,
                jwks_cache_seconds=selected.oidc_jwks_cache_seconds,
                http_timeout_seconds=selected.oidc_http_timeout_seconds,
                clock_skew_seconds=selected.oidc_clock_skew_seconds,
                required_acr=selected.oidc_required_acr,
                require_mfa=selected.oidc_require_mfa,
                max_auth_age_seconds=selected.oidc_max_auth_age_seconds,
            )
            if selected.auth_mode == "oidc"
            else None
        )
        browser_session_codec = (
            BrowserSessionCodec(selected.resolved_browser_session_key or "")
            if selected.browser_auth_enabled
            else None
        )
        browser_oidc_client = (
            BrowserOIDCClient(
                authorization_endpoint=selected.oidc_authorization_endpoint or "",
                token_endpoint=selected.oidc_token_endpoint or "",
                client_id=selected.oidc_client_id or "",
                redirect_uri=selected.oidc_redirect_uri or "",
                scopes=selected.oidc_scope_list,
                client_secret=selected.resolved_oidc_client_secret,
                timeout_seconds=selected.oidc_http_timeout_seconds,
            )
            if selected.browser_auth_enabled
            else None
        )
        app.state.policy = policy
        app.state.corpus_governance = corpus_governance
        app.state.repository = repository
        app.state.semantic_source = semantic_source
        app.state.object_store = object_store
        app.state.quarantine_store = quarantine_store
        app.state.ingestion_jobs = ingestion_jobs
        app.state.query_cache = EvidenceQueryCache(
            selected.retrieval_cache_entries, selected.retrieval_cache_ttl_seconds
        )
        app.state.admission = AdmissionController(
            selected.max_concurrent_answers, selected.admission_wait_ms / 1000
        )
        app.state.ingestion_admission = AdmissionController(
            selected.max_concurrent_ingestions, selected.ingestion_wait_ms / 1000
        )
        app.state.observability = observability
        app.state.oidc_verifier = oidc_verifier
        app.state.browser_session_codec = browser_session_codec
        app.state.browser_oidc_client = browser_oidc_client
        # ACT-001. Built once here rather than per request: each store holds an engine
        # reference, and constructing them in a dependency would mean a new one per call
        # with no benefit. `tenancy_composition` is the only module that names both an
        # application service and its SQL adapter.
        install_tenancy(app.state, selected, repository, policy)

        stop_reconciler = asyncio.Event()

        async def reconcile_loop() -> None:
            while not stop_reconciler.is_set():
                try:
                    await asyncio.to_thread(
                        repository.reconcile_audit_anchor,
                        limit=selected.audit_reconcile_batch_size,
                    )
                    snapshot = await asyncio.to_thread(
                        repository.readiness_snapshot,
                        max_pending_events=selected.audit_max_pending_events,
                        max_pending_age_seconds=selected.audit_max_pending_age_seconds,
                    )
                    pending_events = snapshot["pending_anchor_events"]
                    oldest_pending_seconds = snapshot["oldest_pending_seconds"]
                    # readiness_snapshot is declared dict[str, object]; these two keys
                    # carry int/float (repository.py:1112-1113). Narrowing belongs in the
                    # repository return type, which is out of scope for this change.
                    observability.observe_anchor_backlog(
                        int(pending_events),  # type: ignore[call-overload]
                        float(oldest_pending_seconds),  # type: ignore[arg-type]
                    )
                except Exception as exc:
                    # Readiness exposes the backlog; the metric preserves failure visibility.
                    observability.observe_anchor_reconcile_failure(exc)
                try:
                    await asyncio.wait_for(
                        stop_reconciler.wait(), timeout=selected.audit_reconcile_interval_seconds
                    )
                except TimeoutError:
                    continue

        reconciler = asyncio.create_task(reconcile_loop(), name="audit-anchor-reconciler")
        try:
            yield
        finally:
            stop_reconciler.set()
            await reconciler
            if semantic_source is not None:
                semantic_source.close()
            if browser_oidc_client is not None:
                browser_oidc_client.close()
            if oidc_verifier is not None:
                oidc_verifier.close()
            quarantine_store.close()
            object_store.close()
            observability.close()
            repository.close()

    app = FastAPI(
        title="KORPUS API",
        version=__version__,
        description="Evidence-bound controlled-corpus API",
        lifespan=lifespan,
    )
    app.dependency_overrides[get_settings] = lambda: selected

    @app.middleware("http")
    async def request_identity(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid.uuid4())
        request.state.request_id = request_id
        trace_token = set_trace_id(request_id)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and selected.browser_auth_enabled:
            session_cookie = request.cookies.get(selected.browser_session_cookie)
            if session_cookie:
                codec = getattr(app.state, "browser_session_codec", None)
                try:
                    session = codec.open(session_cookie, expected_kind="session") if codec else {}
                    expected_csrf = session.get("csrf")
                except BrowserSessionError:
                    return JSONResponse({"detail": "invalid browser session"}, status_code=401)
                supplied_csrf = request.headers.get("X-CSRF-Token", "")
                csrf_cookie = request.cookies.get(selected.browser_csrf_cookie, "")
                if (
                    not isinstance(expected_csrf, str)
                    or not supplied_csrf
                    or not csrf_cookie
                    or not secrets.compare_digest(supplied_csrf, expected_csrf)
                    or not secrets.compare_digest(csrf_cookie, expected_csrf)
                ):
                    return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)
        started = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            reset_trace_id(trace_token)
            route = getattr(request.scope.get("route"), "path", "unmatched")
            if hasattr(app.state, "observability"):
                app.state.observability.observe_http(
                    request.method, route, status_code, time.monotonic() - started
                )

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=selected.trusted_host_list)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=selected.cors_origin_list,
        allow_credentials=selected.browser_auth_enabled,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
    )
    app.include_router(router)
    app.include_router(tenancy_router)
    app.include_router(billing_router)
    app.include_router(admin_router)

    # A dependency being down is a "come back shortly", not a 500. Without these, a
    # postgres restart or a MinIO blip reaches the reader as an uncaught exception — a bare
    # stack trace with no Retry-After — and the client cannot tell a transient outage from
    # a permanent break. Mapped to 503 so a soldier's client knows to retry, and so the
    # reason word ("database"/"object_store") never carries an internal detail.
    from sqlalchemy.exc import DBAPIError, OperationalError

    from korpus.application.ports import ObjectStoreUnavailable

    def _unavailable(reason: str) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": {"reason": reason, "retryable": True}},
            headers={"Retry-After": "2"},
        )

    @app.exception_handler(OperationalError)
    @app.exception_handler(DBAPIError)
    async def _database_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
        return _unavailable("database")

    @app.exception_handler(ObjectStoreUnavailable)
    async def _object_store_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
        return _unavailable("object_store")

    return app


app = create_app()
