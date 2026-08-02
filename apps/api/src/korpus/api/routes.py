from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from korpus.application.answer_query import AnswerPolicy, AnswerQuery
from korpus.config import Settings, get_settings
from korpus.domain.access import Principal
from korpus.domain.models import AccessTier, Answer, Query
from korpus.infrastructure.in_memory import (
    EvidenceBoundStubGenerator,
    InMemoryAuditSink,
    StaticPrincipalResolver,
    SystemClock,
)
from korpus.infrastructure.lexical import LexicalRetriever

router = APIRouter()

SettingsDependency = Annotated[Settings, Depends(get_settings)]

# Process-local singletons. Replacing them with database-backed adapters is a wiring
# change here and nowhere else — the domain depends on ports, not on these objects.
# The corpus an unauthenticated caller may read. Named explicitly rather than implied
# by "no corpus filter", because an implied wildcard is how the whole index leaks.
OPEN_CORPUS = UUID("00000000-0000-4000-8000-000000000001")

_retriever = LexicalRetriever()
_audit = InMemoryAuditSink()
_resolver = StaticPrincipalResolver(
    anonymous=Principal(
        subject_id="anonymous",
        tier=AccessTier.PUBLIC,
        authorized_corpora=frozenset({OPEN_CORPUS}),
    )
)
_clock = SystemClock()


def get_resolver() -> StaticPrincipalResolver:
    return _resolver


def answer_service(settings: SettingsDependency) -> AnswerQuery:
    return AnswerQuery(
        retriever=_retriever,
        generator=EvidenceBoundStubGenerator(),
        audit=_audit,
        policy=AnswerPolicy(minimum_score=settings.min_retrieval_score),
        clock=_clock,
    )


async def current_principal(
    resolver: Annotated[StaticPrincipalResolver, Depends(get_resolver)],
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Identity is derived here and nowhere else. A request cannot name its own tier."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip() or None
    return await resolver.resolve(token)


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process answers. Says nothing about readiness to serve."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(settings: SettingsDependency, response: Response) -> dict[str, object]:
    """Readiness, kept distinct from liveness (SYSTEM.md reliability).

    Reports not-ready while the corpus is empty: a system that can only abstain is
    running, but it is not serving.
    """
    corpus_loaded = bool(_retriever.size)
    if not corpus_loaded:
        response.status_code = 503
    # Deliberately no index census: the exact number of indexed spans is information
    # about the corpus, and this endpoint is unauthenticated by design.
    return {
        "status": "ready" if corpus_loaded else "degraded",
        "corpus_loaded": corpus_loaded,
        "environment": settings.environment,
        "generator": settings.llm_provider,
    }


@router.post("/v1/answers", response_model=Answer)
async def create_answer(
    query: Query,
    service: Annotated[AnswerQuery, Depends(answer_service)],
    principal: Annotated[Principal, Depends(current_principal)],
) -> Answer:
    return await service.execute(query, principal)
