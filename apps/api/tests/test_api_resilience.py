"""The service under failure: it degrades, reports, and keeps its response shape."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import CORPUS, make_span
from korpus.api import routes
from korpus.config import Settings
from korpus.infrastructure.resilience import CircuitBreaker, TokenBucket
from korpus.main import create_app


def test_rate_limited_requests_get_a_refusal_not_a_different_shape(client) -> None:  # type: ignore[no-untyped-def]
    """A flood is refused as an answer object, so a client parses one format only."""
    routes._bucket = TokenBucket(capacity=2, refill_per_second=0)
    routes._retriever.add(make_span(text="порядок евакуації поранених"))
    statuses = [
        client.post("/v1/answers", json={"text": "порядок евакуації"}).status_code
        for _ in range(4)
    ]
    assert statuses[:2] == [200, 200]
    assert statuses[2:] == [429, 429]

    limited = client.post("/v1/answers", json={"text": "порядок евакуації"})
    body = limited.json()
    assert body["status"] == "requires_human_review"
    assert body["citations"] == []
    assert set(body) >= {"id", "trace_id", "status", "text", "confidence", "limitations"}


def test_rate_limiting_is_per_subject(client) -> None:  # type: ignore[no-untyped-def]
    from korpus.domain.access import Principal
    from korpus.domain.models import AccessTier

    routes._bucket = TokenBucket(capacity=1, refill_per_second=0)
    routes._resolver._table["operator"] = Principal(
        subject_id="operator-1",
        tier=AccessTier.PUBLIC,
        authorized_corpora=frozenset({CORPUS}),
    )
    assert client.post("/v1/answers", json={"text": "питання перше"}).status_code == 200
    assert client.post("/v1/answers", json={"text": "питання друге"}).status_code == 429
    other = client.post(
        "/v1/answers",
        json={"text": "питання третє"},
        headers={"Authorization": "Bearer operator"},
    )
    assert other.status_code == 200


def test_an_unhandled_error_returns_a_contract_shaped_refusal(tmp_path: Path) -> None:
    """No traceback reaches a caller, and the incident is recorded.

    The client is built with `raise_server_exceptions=False` on purpose: the default
    re-raises inside the test process and would assert on an exception no deployed
    caller ever sees, instead of on the response one does.
    """
    from fastapi.testclient import TestClient

    class ExplodingRetriever:
        size = 1

        async def search(self, *args: object, **kwargs: object) -> list[object]:
            raise MemoryError("simulated adapter failure")

    settings = Settings(
        environment="test",
        log_level="CRITICAL",
        llm_provider="stub",
        corpus_path=tmp_path / "korpus.sqlite3",
    )
    app = create_app(settings)
    routes._retriever = ExplodingRetriever()  # type: ignore[assignment]
    # Process-global by design: a bucket left tripped by another test would refuse
    # this request before the failure under test could happen.
    routes._bucket = TokenBucket()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/v1/answers", json={"text": "порядок евакуації"})
    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "requires_human_review"
    assert body["citations"] == []
    assert "MemoryError" not in json.dumps(body)
    assert "Traceback" not in json.dumps(body)
    assert any(event == "request.unhandled_error" for event, _ in routes._audit.events)


def test_a_dead_generator_trips_the_circuit_and_answers_are_held(client) -> None:  # type: ignore[no-untyped-def]
    class Dead:
        async def compose(self, query: object, evidence: object) -> list[object]:
            raise RuntimeError("provider down")

    routes._breaker = CircuitBreaker(threshold=2)
    routes._retriever.add(make_span(text="порядок евакуації поранених"))
    original = routes.EvidenceBoundStubGenerator
    routes.EvidenceBoundStubGenerator = Dead  # type: ignore[misc,assignment]
    try:
        for _ in range(3):
            body = client.post("/v1/answers", json={"text": "порядок евакуації"}).json()
            assert body["status"] == "requires_human_review"
    finally:
        routes.EvidenceBoundStubGenerator = original  # type: ignore[misc]
    assert routes._breaker.state == "open"
    assert client.get("/ready").json()["generator_circuit"] == "open"


def test_readiness_reports_the_store_and_the_circuit(client) -> None:  # type: ignore[no-untyped-def]
    routes._retriever.add(make_span())
    body = client.get("/ready").json()
    assert body["status"] == "ready"
    assert body["store_healthy"] is True
    assert body["store_recovered"] is False
    assert body["audit_write_failures"] == 0
    assert body["generator_circuit"] == "closed"


def test_the_service_starts_and_serves_after_a_corrupt_store(tmp_path: Path) -> None:
    """The whole recovery path, through the app rather than through the store alone."""
    from fastapi.testclient import TestClient

    settings = Settings(
        environment="test",
        log_level="WARNING",
        llm_provider="stub",
        corpus_path=tmp_path / "korpus.sqlite3",
    )
    routes._bucket = TokenBucket()
    first = create_app(settings)
    routes._store.add(make_span(text="порядок евакуації поранених"), "sha")
    routes._store.close()

    (tmp_path / "korpus.sqlite3").write_bytes(b"corrupted beyond repair" * 50)

    second = create_app(settings)
    assert routes._store.recovered is True
    with TestClient(second) as client:
        ready = client.get("/ready").json()
        assert ready["store_recovered"] is True
        assert ready["store_healthy"] is True
        answer = client.post("/v1/answers", json={"text": "порядок евакуації"}).json()
    assert answer["status"] == "answered"
    assert first is not second


def test_the_index_is_rebuilt_from_the_store_on_start(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        log_level="WARNING",
        llm_provider="stub",
        corpus_path=tmp_path / "korpus.sqlite3",
    )
    create_app(settings)
    routes._store.add(make_span(text="порядок евакуації поранених"), "sha")
    routes._store.close()

    create_app(settings)
    assert routes._retriever.size == 1


def test_rate_limiting_works_before_the_audit_sink_is_wired(client) -> None:  # type: ignore[no-untyped-def]
    """The refusal path must not depend on a component that may not exist yet."""
    routes._audit = None
    routes._bucket = TokenBucket(capacity=0, refill_per_second=0)
    response = client.post("/v1/answers", json={"text": "порядок евакуації"})
    assert response.status_code == 429
    assert response.json()["status"] == "requires_human_review"


def test_the_error_handler_works_before_the_audit_sink_is_wired(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    class ExplodingRetriever:
        size = 1

        async def search(self, *args: object, **kwargs: object) -> list[object]:
            raise MemoryError("simulated adapter failure")

    settings = Settings(
        environment="test",
        log_level="CRITICAL",
        llm_provider="stub",
        corpus_path=tmp_path / "korpus.sqlite3",
    )
    app = create_app(settings)
    routes._retriever = ExplodingRetriever()  # type: ignore[assignment]
    routes._audit = None
    routes._bucket = TokenBucket()
    response = TestClient(app, raise_server_exceptions=False).post(
        "/v1/answers", json={"text": "порядок евакуації"}
    )
    assert response.status_code == 500
    assert response.json()["status"] == "requires_human_review"


def test_readiness_reports_a_broken_store_as_not_serving(client) -> None:  # type: ignore[no-untyped-def]
    """A live process over a dead database is exactly the state that must show red."""

    class DeadStore:
        recovered = False

        def healthy(self) -> bool:
            return False

        def close(self) -> None:
            """Present because the fixture closes whatever store it finds."""

    routes._retriever.add(make_span())
    routes._store = DeadStore()  # type: ignore[assignment]
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["store_healthy"] is False
    assert response.json()["status"] == "degraded"
