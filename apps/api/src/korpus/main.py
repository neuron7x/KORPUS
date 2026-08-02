import logging

from fastapi import FastAPI

from korpus.api.routes import get_resolver, router
from korpus.config import Settings, get_settings


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


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    logging.basicConfig(level=resolved.log_level.upper())
    enforce_startup_invariants(resolved, get_resolver())
    application = FastAPI(
        title="Korpus API",
        version="0.2.0",
        description="Evidence-first retrieval, learning, and document-assistance API.",
    )
    application.include_router(router)
    return application


app = create_app()
