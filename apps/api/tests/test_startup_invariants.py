"""Startup refuses unsafe configurations instead of serving one request with a hole."""

import pytest

from korpus.config import Settings
from korpus.infrastructure.in_memory import StaticPrincipalResolver
from korpus.main import UnsafeConfiguration, enforce_startup_invariants


class RealResolver:
    development_only = False


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "development",
        "log_level": "INFO",
        "llm_provider": "stub",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_development_may_use_the_static_resolver() -> None:
    enforce_startup_invariants(settings(), StaticPrincipalResolver())


def test_production_refuses_the_development_resolver() -> None:
    with pytest.raises(UnsafeConfiguration, match="development-only"):
        enforce_startup_invariants(
            settings(environment="production"), StaticPrincipalResolver()
        )


def test_production_accepts_a_real_resolver() -> None:
    enforce_startup_invariants(settings(environment="production"), RealResolver())


def test_selecting_an_unimplemented_provider_is_a_startup_failure() -> None:
    """The knob exists in config; the adapter does not. Fail at boot, not at answer."""
    for provider in ("openai", "local"):
        with pytest.raises(UnsafeConfiguration, match="no generator adapter"):
            enforce_startup_invariants(
                settings(llm_provider=provider), StaticPrincipalResolver()
            )


def test_stub_provider_is_allowed() -> None:
    enforce_startup_invariants(settings(llm_provider="stub"), StaticPrincipalResolver())


def test_unknown_environment_is_rejected_by_configuration() -> None:
    with pytest.raises(ValueError):
        settings(environment="prod-ish")


def test_unknown_provider_is_rejected_by_configuration() -> None:
    with pytest.raises(ValueError):
        settings(llm_provider="claude")


def test_thresholds_are_bounded_by_configuration() -> None:
    with pytest.raises(ValueError):
        Settings(min_retrieval_score=1.5)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        Settings(min_citation_coverage=-0.1)  # type: ignore[call-arg]
