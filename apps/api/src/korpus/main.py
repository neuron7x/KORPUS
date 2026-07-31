from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from korpus.api.routes import router
from korpus.application.policy import PolicyEngine
from korpus.config import Settings, get_settings
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.repository import SqlRepository


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
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
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
