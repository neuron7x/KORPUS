from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from korpus.application.answer_query import AnswerPolicy, AnswerQuery
from korpus.config import Settings, get_settings
from korpus.domain.access import Principal
from korpus.domain.models import AccessTier, Answer, AnswerStatus, Query
from korpus.infrastructure.in_memory import (
    EvidenceBoundStubGenerator,
    StaticPrincipalResolver,
    SystemClock,
)
from korpus.infrastructure.lexical import LexicalRetriever
from korpus.infrastructure.resilience import (
    CircuitBreaker,
    DurableAuditSink,
    GuardedGenerator,
    TokenBucket,
    utcnow,
)
from korpus.infrastructure.store import CorpusStore

router = APIRouter()

SettingsDependency = Annotated[Settings, Depends(get_settings)]

# The corpus an unauthenticated caller may read. Named explicitly rather than implied
# by "no corpus filter", because an implied wildcard is how the whole index leaks.
OPEN_CORPUS = UUID("00000000-0000-4000-8000-000000000001")

RATE_LIMITED_TEXT = "Забагато запитів. Спробуйте за хвилину."

# Process-local wiring. Replacing these with database-backed adapters is a change
# here and nowhere else — the domain depends on ports, not on these objects.
_retriever = LexicalRetriever()
_store: CorpusStore | None = None
_audit: DurableAuditSink | None = None
_resolver = StaticPrincipalResolver(
    anonymous=Principal(
        subject_id="anonymous",
        tier=AccessTier.PUBLIC,
        authorized_corpora=frozenset({OPEN_CORPUS}),
    )
)
_clock = SystemClock()
_breaker = CircuitBreaker()
_bucket = TokenBucket()


def get_resolver() -> StaticPrincipalResolver:
    return _resolver


def answer_service(settings: SettingsDependency) -> AnswerQuery:
    return AnswerQuery(
        retriever=_retriever,
        generator=GuardedGenerator(EvidenceBoundStubGenerator(), _breaker),
        audit=_audit,  # type: ignore[arg-type]  # None only before create_app wires it
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

    Reports not-ready while the corpus is empty or the store is unhealthy: a system
    that can only abstain is running, but it is not serving. Deliberately no index
    census — the number of indexed spans is information about the corpus, and this
    endpoint is unauthenticated by design.
    """
    corpus_loaded = bool(_retriever.size)
    store_healthy = _store.healthy() if _store is not None else False
    serving = corpus_loaded and store_healthy
    if not serving:
        response.status_code = 503
    return {
        "status": "ready" if serving else "degraded",
        "corpus_loaded": corpus_loaded,
        "store_healthy": store_healthy,
        "store_recovered": bool(_store.recovered) if _store is not None else False,
        "audit_write_failures": _audit.write_failures if _audit is not None else 0,
        "generator_circuit": _breaker.state,
        "environment": settings.environment,
        "generator": settings.llm_provider,
    }


@router.post("/v1/answers", response_model=Answer)
async def create_answer(
    query: Query,
    service: Annotated[AnswerQuery, Depends(answer_service)],
    principal: Annotated[Principal, Depends(current_principal)],
    response: Response,
) -> Answer:
    if not _bucket.allow(principal.subject_id, utcnow()):
        response.status_code = 429
        if _audit is not None:
            await _audit.record("request.rate_limited", {"subject_id": principal.subject_id})
        # Still a contract-valid answer object: a client parsing the refusal must not
        # have to handle a second, differently shaped error body.
        return Answer(
            status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
            text=RATE_LIMITED_TEXT,
            confidence=0,
            limitations=["Перевищено дозволену частоту запитів."],
        )
    return await service.execute(query, principal)
