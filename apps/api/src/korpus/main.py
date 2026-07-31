from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from korpus.api.routes import router
from korpus.application.cache import EvidenceQueryCache
from korpus.application.policy import PolicyEngine
from korpus.application.resilience import AdmissionController
from korpus.config import Settings, get_settings
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.observability import Observability
from korpus.infrastructure.repository import SqlRepository
from korpus.security.oidc import OIDCVerifier


def create_app(settings: Settings | None = None) -> FastAPI:
    selected = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        policy = PolicyEngine()
        repository = SqlRepository(
            selected.database_url,
            selected.resolved_audit_hmac_key,
            policy,
            selected.audit_anchor_path,
        )
        repository.initialize(create_schema=selected.schema_mode == "auto")
        app.state.policy = policy
        app.state.repository = repository
        app.state.object_store = LocalObjectStore(selected.object_root)
        app.state.query_cache = EvidenceQueryCache(
            selected.retrieval_cache_entries, selected.retrieval_cache_ttl_seconds
        )
        app.state.admission = AdmissionController(
            selected.max_concurrent_answers, selected.admission_wait_ms / 1000
        )
        app.state.observability = Observability(
            service_name=selected.service_name, otlp_endpoint=selected.otlp_endpoint
        )
        app.state.oidc_verifier = (
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
        yield
        repository.engine.dispose()

    app = FastAPI(
        title="KORPUS API",
        version="2.0.0",
        description="Evidence-bound controlled-corpus API",
        lifespan=lifespan,
    )
    app.dependency_overrides[get_settings] = lambda: selected

    @app.middleware("http")
    async def request_identity(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:128]
        started = time.monotonic()
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        route = getattr(request.scope.get("route"), "path", "unmatched")
        app.state.observability.observe_http(
            request.method, route, response.status_code, time.monotonic() - started
        )
        return response

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
