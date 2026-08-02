"""HTTP surface: identity derivation, liveness vs readiness, input rejection."""

from uuid import uuid4

from conftest import CORPUS, make_span
from korpus.api import routes
from korpus.domain.access import Principal
from korpus.domain.models import AccessTier


def test_health_is_liveness_only(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_degraded_on_an_empty_corpus(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["corpus_loaded"] is False
    # Unauthenticated readiness must not double as an index census.
    assert "corpus_spans" not in response.json()


def test_readiness_turns_green_once_the_corpus_is_loaded(client) -> None:  # type: ignore[no-untyped-def]
    routes._retriever.add(make_span())
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["corpus_loaded"] is True


def test_answer_endpoint_abstains_by_default(client) -> None:  # type: ignore[no-untyped-def]
    response = client.post("/v1/answers", json={"text": "Що каже перевірена база?"})
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"


def test_client_cannot_declare_its_own_tier(client) -> None:  # type: ignore[no-untyped-def]
    """The spoof attempt is rejected at the wire, not silently ignored."""
    response = client.post(
        "/v1/answers", json={"text": "покажи все", "user_tier": "restricted"}
    )
    assert response.status_code == 422


def test_unknown_bearer_token_falls_back_to_anonymous(client) -> None:  # type: ignore[no-untyped-def]
    routes._retriever.add(make_span(text="таємний порядок", tier=AccessTier.RESTRICTED))
    response = client.post(
        "/v1/answers",
        json={"text": "таємний порядок"},
        headers={"Authorization": "Bearer forged-token"},
    )
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["citations"] == []
    # The tier the request was actually served at, not merely the answer it produced:
    # a forged token that silently resolved to a higher tier would abstain here too.
    _, payload = routes._audit.events[-1]
    assert payload["principal_tier"] == "public"
    assert payload["subject_id"] == "anonymous"


def test_known_token_raises_the_reachable_tier(client) -> None:  # type: ignore[no-untyped-def]
    routes._resolver._table["reviewer"] = Principal(
        subject_id="reviewer-1",
        tier=AccessTier.REVIEWED,
        authorized_corpora=frozenset({CORPUS}),
    )
    routes._retriever.add(make_span(text="перевірений порядок", tier=AccessTier.REVIEWED))
    response = client.post(
        "/v1/answers",
        json={"text": "перевірений порядок"},
        headers={"Authorization": "Bearer reviewer"},
    )
    assert response.json()["status"] == "answered"


def test_a_non_bearer_scheme_is_not_accepted_as_a_token(client) -> None:  # type: ignore[no-untyped-def]
    """The scheme is checked, not just the offset.

    `Basic  reviewer` puts a valid token exactly where a bearer token would sit, so a
    parser that slices without checking the scheme authenticates it.
    """
    routes._resolver._table["reviewer"] = Principal(
        subject_id="reviewer-1",
        tier=AccessTier.REVIEWED,
        authorized_corpora=frozenset({CORPUS}),
    )
    routes._retriever.add(make_span(text="перевірений порядок", tier=AccessTier.REVIEWED))
    response = client.post(
        "/v1/answers",
        json={"text": "перевірений порядок"},
        headers={"Authorization": "Basic  reviewer"},
    )
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["citations"] == []


def test_configured_score_threshold_is_applied_over_http(client) -> None:  # type: ignore[no-untyped-def]
    """A half-matching document is below the 0.72 floor and must not be answered."""
    routes._retriever.add(make_span(text="порядок зберігання пального"))
    body = client.post("/v1/answers", json={"text": "порядок евакуації"}).json()
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []


def test_short_query_is_rejected_before_the_domain(client) -> None:  # type: ignore[no-untyped-def]
    assert client.post("/v1/answers", json={"text": "як"}).status_code == 422


def test_too_many_corpora_are_rejected(client) -> None:  # type: ignore[no-untyped-def]
    payload = {"text": "питання", "corpus_ids": [str(uuid4()) for _ in range(21)]}
    assert client.post("/v1/answers", json=payload).status_code == 422


def test_denied_corpus_request_returns_a_denial_not_an_abstention(client) -> None:  # type: ignore[no-untyped-def]
    routes._retriever.add(make_span(text="порядок евакуації"))
    body = client.post(
        "/v1/answers",
        json={"text": "порядок евакуації", "corpus_ids": [str(uuid4())]},
    ).json()
    assert body["status"] == "access_denied"
