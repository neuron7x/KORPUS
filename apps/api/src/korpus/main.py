from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response

from korpus.api.routes import router
from korpus.application.cache import EvidenceQueryCache
from korpus.application.policy import PolicyEngine
from korpus.application.resilience import AdmissionController
from korpus.config import Settings, get_settings
from korpus.infrastructure.observability import Observability
from korpus.infrastructure.runtime import create_object_store, create_repository
from korpus.infrastructure.semantic import HttpEmbeddingProvider, PgVectorSemanticIndex
from korpus.security.oidc import OIDCVerifier

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def create_app(settings: Settings | None = None) -> FastAPI:
    selected = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        policy = PolicyEngine()
        repository = create_repository(selected, policy)
        repository.initialize(create_schema=selected.schema_mode == "auto")
        object_store = create_object_store(selected)
        observability = Observability(
            service_name=selected.service_name, otlp_endpoint=selected.otlp_endpoint
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
            )
            if selected.auth_mode == "oidc"
            else None
        )
        app.state.policy = policy
        app.state.repository = repository
        app.state.semantic_source = semantic_source
        app.state.object_store = object_store
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
                    observability.observe_anchor_backlog(
                        int(snapshot["pending_anchor_events"]),
                        float(snapshot["oldest_pending_seconds"]),
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
            if oidc_verifier is not None:
                oidc_verifier.close()
            object_store.close()
            observability.close()
            repository.close()

    app = FastAPI(
        title="KORPUS API",
        version="4.0.0",
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
            route = getattr(request.scope.get("route"), "path", "unmatched")
            if hasattr(app.state, "observability"):
                app.state.observability.observe_http(
                    request.method, route, status_code, time.monotonic() - started
                )

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=selected.trusted_host_list)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=selected.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    app.include_router(router)
    return app


app = create_app()
