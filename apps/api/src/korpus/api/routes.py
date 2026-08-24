"""Aggregate the bounded API surfaces without owning endpoint behavior."""

from __future__ import annotations

from fastapi import APIRouter

from korpus.api.routes_answers import router as answers_router
from korpus.api.routes_audit import router as audit_router
from korpus.api.routes_auth import router as auth_router
from korpus.api.routes_client import router as client_router
from korpus.api.routes_corpus import router as corpus_router
from korpus.api.routes_health import router as health_router
from korpus.api.routes_inference import router as inference_router
from korpus.api.routes_offline import router as offline_router
from korpus.api.routes_review import router as review_router

router = APIRouter()
for bounded_router in (
    health_router,
    auth_router,
    client_router,
    corpus_router,
    review_router,
    answers_router,
    inference_router,
    offline_router,
    audit_router,
):
    router.include_router(bounded_router)
