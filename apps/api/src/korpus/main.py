import logging
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from korpus.api import routes
from korpus.api.routes import get_resolver, router
from korpus.config import Settings, get_settings
from korpus.domain.models import Answer, AnswerStatus
from korpus.infrastructure.lexical import LexicalRetriever
from korpus.infrastructure.resilience import CircuitBreaker, DurableAuditSink, TokenBucket
from korpus.infrastructure.store import CorpusStore

log = logging.getLogger(__name__)

INTERNAL_TEXT = "Внутрішня помилка. Відповідь не видано, подію зафіксовано."


class UnsafeConfiguration(RuntimeError):
    """Raised at startup rather than answering one request with a hole in it."""


def enforce_startup_invariants(settings: Settings, resolver: object) -> None:
    """Fail closed at boot.

    Two conditions make this deployment unsafe rather than merely incomplete: a
    development identity table in production, and a model provider selected while no
    adapter for it exists. Both are startup failures, never runtime surprises.
    """
    if settings.environment == "production" and getattr(resolver, "development_only", False):
        raise UnsafeConfiguration(
            "production requires a real principal resolver; "
            "StaticPrincipalResolver is development-only"
        )
    if settings.llm_provider != "stub":
        raise UnsafeConfiguration(
            f"no generator adapter is implemented for provider "
            f"'{settings.llm_provider}'; only 'stub' can be served today"
        )


def open_corpus(settings: Settings) -> tuple[CorpusStore, LexicalRetriever, int]:
    """Open the store, self-heal if needed, and build the in-memory index from it.

    A corrupt database is quarantined and replayed from the journal inside
    CorpusStore; here the only decision left is whether the process can serve. It
    starts either way — a system that refuses to boot after a bad shutdown is a
    system that is down when it is needed most — and reports itself degraded through
    /ready until a corpus is present.
    """
    store = CorpusStore(Path(settings.corpus_path))
    retriever = LexicalRetriever()
    loaded = 0
    for span in store.spans():
        retriever.add(span)
        loaded += 1
    if store.recovered:
        log.error("corpus store was recovered on startup; %d chunks re-indexed", loaded)
    return store, retriever, loaded


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    logging.basicConfig(level=resolved.log_level.upper())
    enforce_startup_invariants(resolved, get_resolver())

    store, retriever, loaded = open_corpus(resolved)
    routes._store = store
    routes._retriever = retriever
    routes._audit = DurableAuditSink(store)
    # Operational limits come from configuration, not from the defaults baked into
    # the primitives: an operator changing them must not have to change the code.
    routes._breaker = CircuitBreaker(
        threshold=resolved.circuit_failure_threshold,
        cooldown=timedelta(seconds=resolved.circuit_cooldown_seconds),
    )
    routes._bucket = TokenBucket(
        capacity=resolved.rate_limit_burst,
        refill_per_second=resolved.rate_limit_per_second,
    )

    application = FastAPI(
        title="Korpus API",
        version="0.3.0",
        description="Evidence-first retrieval, learning, and document-assistance API.",
    )
    application.include_router(router)
    # The app serves the same Settings object that was just validated. Without this
    # override the dependency resolves get_settings() again and a caller-tightened
    # configuration — including the one the startup guard just checked — is discarded.
    application.dependency_overrides[get_settings] = lambda: resolved

    @application.exception_handler(Exception)
    async def unhandled(request: Request, error: Exception) -> JSONResponse:
        """No traceback ever reaches a caller, and no request ends shapeless.

        An unhandled error returns the same object shape as every other refusal, so a
        client has exactly one response format to parse, and the incident is recorded
        with the path rather than with the attacker-controlled body.
        """
        log.exception("unhandled error on %s", request.url.path)
        if routes._audit is not None:
            await routes._audit.record(
                "request.unhandled_error",
                {"path": request.url.path, "error": type(error).__name__},
            )
        answer = Answer(
            status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
            text=INTERNAL_TEXT,
            confidence=0,
            limitations=["Запит не оброблено через внутрішню помилку."],
        )
        return JSONResponse(status_code=500, content=answer.model_dump(mode="json"))

    log.info("korpus started: %d chunks indexed from %s", loaded, resolved.corpus_path)
    return application


app = create_app()
