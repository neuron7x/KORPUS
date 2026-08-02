"""Startup refuses unsafe configurations instead of serving one request with a hole."""

from pathlib import Path

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
        "corpus_path": Path("/tmp/korpus-settings-probe.sqlite3"),
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
        Settings(min_retrieval_score=-0.1)  # type: ignore[call-arg]


def test_create_app_serves_the_settings_it_validated() -> None:
    """The guard is worthless if the app then resolves its own configuration.

    A tightened threshold passed to create_app used to be discarded: the dependency
    called get_settings() again and served the process defaults instead.
    """
    from conftest import CORPUS, make_span
    from fastapi.testclient import TestClient
    from korpus.api import routes
    from korpus.domain.access import Principal
    from korpus.domain.models import AccessTier
    from korpus.infrastructure.in_memory import InMemoryAuditSink, StaticPrincipalResolver
    from korpus.infrastructure.lexical import LexicalRetriever
    from korpus.infrastructure.resilience import TokenBucket
    from korpus.main import create_app

    routes._resolver = StaticPrincipalResolver(
        anonymous=Principal(
            subject_id="anonymous",
            tier=AccessTier.PUBLIC,
            authorized_corpora=frozenset({CORPUS}),
        )
    )
    strict = settings(min_retrieval_score=0.99)
    app = create_app(strict)
    # After create_app: it rebuilds the index from the store, and an empty corpus
    # would abstain for the wrong reason — hiding whether the threshold was applied.
    routes._retriever = LexicalRetriever([make_span(text="порядок евакуації поранених")])
    routes._audit = InMemoryAuditSink()
    routes._bucket = TokenBucket()
    with TestClient(app) as client:
        # Three of four query terms match: 0.75 — above the default floor, below 0.99.
        body = client.post(
            "/v1/answers", json={"text": "порядок евакуації поранених негайно"}
        ).json()
    assert body["status"] == "insufficient_evidence"


def test_env_file_is_anchored_to_the_repository() -> None:
    """A relative env_file means the production guard silently misses the file."""
    env_file = Settings.model_config.get("env_file")
    assert env_file is not None
    assert Path(str(env_file)).is_absolute()
    assert Path(str(env_file)).name == ".env"


async def test_audit_sink_is_bounded() -> None:
    from korpus.infrastructure.in_memory import InMemoryAuditSink

    sink = InMemoryAuditSink(capacity=10)
    for index in range(50):
        await sink.record("answer.completed", {"n": index})
    assert len(sink.events) == 10
    assert sink.events[-1][1]["n"] == 49


def test_operational_limits_are_bounded_by_configuration() -> None:
    """Every knob an operator can turn has an edge it cannot be turned past."""
    for field, value in (
        ("max_answer_spans", 0),
        ("max_answer_spans", 51),
        ("candidate_multiplier", 0),
        ("generator_timeout_seconds", 0),
        ("generator_timeout_seconds", 301),
        ("rate_limit_burst", 0),
        ("rate_limit_per_second", -1),
        ("circuit_failure_threshold", 0),
        ("circuit_cooldown_seconds", 0),
        ("max_search_results", 0),
        ("max_search_results", 101),
    ):
        with pytest.raises(ValueError):
            settings(**{field: value})


def test_configured_limits_reach_the_running_service(tmp_path: Path) -> None:
    """A knob that changes nothing is worse than no knob: it invites a false belief."""
    from conftest import CORPUS, make_span
    from fastapi.testclient import TestClient
    from korpus.api import routes
    from korpus.domain.access import Principal
    from korpus.domain.models import AccessTier
    from korpus.infrastructure.in_memory import StaticPrincipalResolver
    from korpus.infrastructure.lexical import LexicalRetriever
    from korpus.main import create_app

    configured = settings(
        corpus_path=tmp_path / "korpus.sqlite3",
        max_answer_spans=2,
        rate_limit_burst=1,
        rate_limit_per_second=0,
        circuit_failure_threshold=1,
    )
    app = create_app(configured)
    assert routes._bucket.capacity == 1
    assert routes._breaker.threshold == 1

    routes._resolver = StaticPrincipalResolver(
        anonymous=Principal(
            subject_id="anonymous",
            tier=AccessTier.PUBLIC,
            authorized_corpora=frozenset({CORPUS}),
        )
    )
    routes._retriever = LexicalRetriever(
        [make_span(text="порядок евакуації поранених") for _ in range(5)]
    )
    client = TestClient(app)
    answer = client.post("/v1/answers", json={"text": "порядок евакуації"}).json()
    assert len(answer["citations"]) == 2
    assert client.post("/v1/answers", json={"text": "порядок евакуації"}).status_code == 429
