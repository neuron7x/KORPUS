"""Browsing the corpus: the same gate as an answer, with no model in the path."""

from __future__ import annotations

import json
from uuid import uuid4

from conftest import CORPUS, make_span
from korpus.api import routes
from korpus.domain.access import Principal
from korpus.domain.models import AccessTier, AuthorityClass, ReviewState


def test_search_returns_the_source_a_reader_may_open(client) -> None:  # type: ignore[no-untyped-def]
    span = make_span(text="порядок евакуації поранених")
    routes._retriever.add(span)
    body = client.post("/v1/search", json={"text": "порядок евакуації"}).json()
    assert body["status"] == "answered"
    assert body["results"][0]["citation"]["chunk_id"] == str(span.chunk_id)
    assert body["results"][0]["authority"] == "official_ua"
    assert 0 < body["results"][0]["score"] <= 1


def test_search_finds_nothing_when_the_corpus_holds_nothing(client) -> None:  # type: ignore[no-untyped-def]
    body = client.post("/v1/search", json={"text": "радіочастотний план"}).json()
    assert body["status"] == "insufficient_evidence"
    assert body["results"] == []


def test_search_never_returns_unapproved_material(client) -> None:  # type: ignore[no-untyped-def]
    """Browsing is not a way around the review workflow."""
    routes._retriever.add(
        make_span(text="порядок евакуації поранених", review=ReviewState.QUARANTINED)
    )
    body = client.post("/v1/search", json={"text": "порядок евакуації"}).json()
    assert body["status"] == "insufficient_evidence"
    assert body["results"] == []


def test_search_never_returns_material_above_the_readers_tier(client) -> None:  # type: ignore[no-untyped-def]
    secret = make_span(text="таємний порядок евакуації", tier=AccessTier.RESTRICTED)
    routes._retriever.add(secret)
    response = client.post("/v1/search", json={"text": "таємний порядок"})
    serialized = json.dumps(response.json(), ensure_ascii=False)
    assert response.json()["results"] == []
    assert str(secret.chunk_id) not in serialized
    assert secret.citation.quote not in serialized


def test_search_reaches_restricted_material_for_an_authorised_reader(client) -> None:  # type: ignore[no-untyped-def]
    secret = make_span(text="таємний порядок евакуації", tier=AccessTier.RESTRICTED)
    routes._retriever.add(secret)
    routes._resolver.trust(
        "cmd",
        Principal(
            subject_id="commander",
            tier=AccessTier.RESTRICTED,
            authorized_corpora=frozenset({CORPUS}),
        ),
    )
    body = client.post(
        "/v1/search",
        json={"text": "таємний порядок"},
        headers={"Authorization": "Bearer cmd"},
    ).json()
    assert body["status"] == "answered"
    assert body["results"][0]["citation"]["chunk_id"] == str(secret.chunk_id)


def test_search_denies_a_corpus_the_reader_does_not_hold(client) -> None:  # type: ignore[no-untyped-def]
    routes._retriever.add(make_span(text="порядок евакуації поранених"))
    body = client.post(
        "/v1/search",
        json={"text": "порядок евакуації", "corpus_ids": [str(uuid4())]},
    ).json()
    assert body["status"] == "access_denied"
    assert body["results"] == []


def test_search_orders_by_authority_not_by_score(client) -> None:  # type: ignore[no-untyped-def]
    analytical = make_span(
        text="порядок евакуації поранених негайно", authority=AuthorityClass.ANALYTICAL
    )
    official = make_span(text="порядок евакуації поранених", authority=AuthorityClass.OFFICIAL_UA)
    routes._retriever.add(analytical)
    routes._retriever.add(official)
    body = client.post(
        "/v1/search", json={"text": "порядок евакуації поранених негайно"}
    ).json()
    assert body["results"][0]["citation"]["chunk_id"] == str(official.chunk_id)


def test_search_works_while_the_generator_circuit_is_open(client) -> None:  # type: ignore[no-untyped-def]
    """The degraded mode this endpoint exists for."""
    from korpus.infrastructure.resilience import CircuitBreaker

    routes._breaker = CircuitBreaker(threshold=1)
    routes._breaker.record_failure(routes._clock.now())
    routes._retriever.add(make_span(text="порядок евакуації поранених"))

    assert client.get("/ready").json()["generator_circuit"] == "open"
    body = client.post("/v1/search", json={"text": "порядок евакуації"}).json()
    assert body["status"] == "answered"
    assert body["results"]


def test_search_reports_truncation_when_more_was_retrieved(client) -> None:  # type: ignore[no-untyped-def]
    for _ in range(6):
        routes._retriever.add(make_span(text="порядок евакуації поранених"))
    routes._store.close()
    from korpus.config import Settings
    from korpus.main import create_app

    settings = Settings(  # type: ignore[call-arg]
        environment="test",
        log_level="CRITICAL",
        llm_provider="stub",
        corpus_path=routes._store.path,
        max_search_results=2,
    )
    app = create_app(settings)
    from fastapi.testclient import TestClient

    for _ in range(6):
        routes._retriever.add(make_span(text="порядок евакуації поранених"))
    body = TestClient(app).post("/v1/search", json={"text": "порядок евакуації"}).json()
    assert len(body["results"]) == 2
    assert body["truncated"] is True


def test_search_is_rate_limited_like_every_other_entry_point(client) -> None:  # type: ignore[no-untyped-def]
    from korpus.infrastructure.resilience import TokenBucket

    routes._bucket = TokenBucket(capacity=1, refill_per_second=0)
    routes._retriever.add(make_span(text="порядок евакуації поранених"))
    assert client.post("/v1/search", json={"text": "порядок евакуації"}).status_code == 200
    throttled = client.post("/v1/search", json={"text": "порядок евакуації"})
    assert throttled.status_code == 429
    assert throttled.json()["results"] == []


def test_search_records_what_it_showed(client) -> None:  # type: ignore[no-untyped-def]
    routes._retriever.add(make_span(text="порядок евакуації поранених"))
    client.post("/v1/search", json={"text": "порядок евакуації"})
    event, payload = routes._audit.events[-1]
    assert event == "search.completed"
    assert payload["status"] == "answered"
    assert payload["results"] == 1
    assert payload["subject_id"] == "anonymous"


def test_search_holds_for_review_when_the_index_returns_forbidden_material(client) -> None:  # type: ignore[no-untyped-def]
    """Same defence in depth as the answer path: a broken adapter shows nothing."""

    class LeakingRetriever:
        size = 1

        async def search(self, *args: object, **kwargs: object) -> list[object]:
            return [make_span(text="таємне", tier=AccessTier.RESTRICTED)]

    routes._retriever = LeakingRetriever()  # type: ignore[assignment]
    body = client.post("/v1/search", json={"text": "таємне"}).json()
    assert body["status"] == "requires_human_review"
    assert body["results"] == []


def test_search_still_answers_before_the_audit_sink_is_wired(client) -> None:  # type: ignore[no-untyped-def]
    routes._audit = None
    routes._retriever.add(make_span(text="порядок евакуації поранених"))
    body = client.post("/v1/search", json={"text": "порядок евакуації"}).json()
    assert body["status"] == "answered"
