from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
        repository = SqlRepository(selected.database_url, selected.resolved_audit_hmac_key, policy)
        repository.initialize()
        app.state.policy = policy
        app.state.repository = repository
        app.state.object_store = LocalObjectStore(selected.object_root)
        yield

    app = FastAPI(
        title="KORPUS API",
        version="1.0.0",
        description="Evidence-bound controlled-corpus API",
        lifespan=lifespan,
    )
    app.dependency_overrides[get_settings] = lambda: selected
    app.add_middleware(
        CORSMiddleware,
        allow_origins=selected.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()
