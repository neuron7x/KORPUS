from __future__ import annotations

from datetime import date

from apps.api.tests.conftest import set_identity
from apps.api.tests.helpers import approve, ingest_text


def test_public_identity_cannot_request_restricted_corpus(client, public_identity):
    set_identity(client, public_identity)
    response = client.post(
        "/v1/answers",
        json={"text": "секретний порядок", "corpus_ids": ["restricted-demo"]},
    )
    assert response.status_code == 403


def test_restricted_document_never_enters_public_retrieval(client, admin_identity, public_identity):
    set_identity(client, admin_identity)
    result = ingest_text(
        client,
        title="Restricted procedure",
        corpus_id="restricted-demo",
        access_tier=3,
        text="Секретний маркер ALPHA-RESTRICTED не можна показувати публічним користувачам.",
    )
    approve(client, result["version"]["id"])

    repository = client.app.state.repository
    public_rows = repository.list_retrievable_spans(
        public_identity, frozenset({"public"}), date.today()
    )
    assert all(document.corpus_id == "public" for _, document, _ in public_rows)

    set_identity(client, public_identity)
    response = client.post("/v1/answers", json={"text": "ALPHA-RESTRICTED"})
    serialized = response.text
    assert response.json()["status"] == "insufficient_evidence"
    assert "ALPHA-RESTRICTED" not in serialized
    assert response.json()["citations"] == []


def test_restricted_corpus_update_does_not_change_public_release(
    client, admin_identity, public_identity
):
    set_identity(client, public_identity)
    before = client.post("/v1/answers", json={"text": "невідомий публічний запит"}).json()[
        "corpus_release"
    ]

    set_identity(client, admin_identity)
    restricted = ingest_text(
        client,
        title="Restricted delta",
        corpus_id="restricted-demo",
        access_tier=3,
        text="RESTRICTED-DELTA-ONLY",
    )
    approve(client, restricted["version"]["id"])

    set_identity(client, public_identity)
    after = client.post("/v1/answers", json={"text": "невідомий публічний запит"}).json()[
        "corpus_release"
    ]
    assert before == after


def test_access_is_monotone_in_clearance(
    client, admin_identity, authenticated_identity, public_identity
):
    set_identity(client, admin_identity)
    public = ingest_text(client, title="Public", text="PUBLIC-MARKER доступний усім.")
    approve(client, public["version"]["id"])
    training = ingest_text(
        client,
        title="Internal",
        corpus_id="training",
        access_tier=1,
        classification="internal",
        text="INTERNAL-MARKER доступний автентифікованим.",
    )
    approve(client, training["version"]["id"])

    repository = client.app.state.repository
    public_rows = repository.list_retrievable_spans(
        public_identity, public_identity.corpora, date.today()
    )
    auth_rows = repository.list_retrievable_spans(
        authenticated_identity, authenticated_identity.corpora, date.today()
    )
    admin_rows = repository.list_retrievable_spans(
        admin_identity, admin_identity.corpora, date.today()
    )
    public_ids = {span.id for span, _, _ in public_rows}
    auth_ids = {span.id for span, _, _ in auth_rows}
    admin_ids = {span.id for span, _, _ in admin_rows}
    assert public_ids <= auth_ids <= admin_ids


def test_access_tier_is_enforced_in_repository_even_for_public_classification(
    client, admin_identity, public_identity
):
    set_identity(client, admin_identity)
    result = ingest_text(
        client,
        title="Tier-only restricted document",
        corpus_id="public",
        access_tier=3,
        classification="public",
        text="TIER-ONLY-SECRET must never enter public candidate memory.",
    )
    approve(client, result["version"]["id"])
    rows = client.app.state.repository.list_retrievable_spans(
        public_identity, frozenset({"public"}), date.today()
    )
    assert all("TIER-ONLY-SECRET" not in span.text for span, _, _ in rows)
