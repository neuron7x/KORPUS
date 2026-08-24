"""A version may only be superseded by a successor of its own document.

Destruction stage B3. `active_superseder` matches on `supersedes_version_id` alone, so
a version in any corpus declaring itself the successor of an approved version of
another document removed that version from retrieval while it stayed `is_current=True`
in the database. Reproduced: an attacker holding only `training` made a `public` order
unanswerable without ever being able to read it.

The ingest path for a *new version of an existing document* checks ownership
(`ingestion.py`); the path that creates a new document did not, and the SQL that
consumes the edge does not re-check it. Both places are asserted here: the application
must refuse the edge, and the projection must ignore an edge that crosses documents
even if one is somehow present.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from korpus.domain.models import Identity
from sqlalchemy import text

from apps.api.tests.conftest import privileged_connection
from apps.api.tests.helpers import approve, ingest_text

VICTIM_MARKER = "ПОТЕРПІЛИЙ"


def _ingest_new_document_claiming_supersession(
    client: TestClient, victim_version_id: str
) -> Any:
    return client.post(
        "/v1/documents/ingest",
        data={
            "document_json": json.dumps(
                {
                    "canonical_title": "Сторонній документ",
                    "corpus_id": "public",
                    "issuer": "Authorized Test Authority",
                    "jurisdiction": "UA",
                    "document_type": "order",
                    "access_tier": 0,
                    "classification": "public",
                }
            ),
            "version_json": json.dumps(
                {
                    "revision": "1.0",
                    "publication_identifier": "FOREIGN-1.0",
                    "authority": "official_ua",
                    "supersedes_version_id": victim_version_id,
                }
            ),
        },
        files={"file": ("foreign.txt", b"Foreign document body.", "text/plain")},
    )


def test_a_new_document_cannot_declare_itself_successor_of_another(
    client: TestClient,
) -> None:
    victim = ingest_text(
        client,
        title="Наказ потерпілого",
        text=f"Журнал {VICTIM_MARKER} ведеться у підрозділі щодоби.",
    )
    victim_version_id = victim["version"]["id"]
    approve(client, victim_version_id)

    response = _ingest_new_document_claiming_supersession(client, victim_version_id)

    assert response.status_code in {400, 409, 422}, response.text


def test_the_victim_stays_answerable_after_the_attempt(client: TestClient) -> None:
    """The property the reader cares about, stated separately from the status code."""
    victim = ingest_text(
        client,
        title="Наказ потерпілого",
        text=f"Журнал {VICTIM_MARKER} ведеться у підрозділі щодоби.",
    )
    victim_version_id = victim["version"]["id"]
    approve(client, victim_version_id)
    before = client.post("/v1/answers", json={"text": f"як ведеться журнал {VICTIM_MARKER}"}).json()
    assert before["status"] == "answered", before["decision_reason"]

    attack = _ingest_new_document_claiming_supersession(client, victim_version_id)
    if attack.status_code == 201:
        # The edge only bites once the foreign version is approved, and approving one's
        # own upload is an ordinary curator action — the attack is not complete until
        # it is taken.
        approve(client, attack.json()["version"]["id"])

    after = client.post("/v1/answers", json={"text": f"як ведеться журнал {VICTIM_MARKER}"}).json()
    assert after["status"] == "answered", (
        "a foreign document must not be able to take an approved order out of retrieval: "
        f"{after['decision_reason']}"
    )


def test_a_crossing_edge_already_in_the_database_is_not_honoured(
    client: TestClient, admin_identity: Identity
) -> None:
    """The second line, stated where the application layer can no longer reach.

    With ingest refusing to write a crossing edge, the SQL filter that consumes it can
    be weakened without any behaviour changing — the state it guards is unreachable
    through the API. The row is therefore written directly, which is exactly the state
    a bulk import, a migration or a future path that forgets the check would produce.
    """
    victim = ingest_text(
        client,
        title="Наказ потерпілого",
        text=f"Журнал {VICTIM_MARKER} ведеться у підрозділі щодоби.",
    )
    victim_version_id = victim["version"]["id"]
    approve(client, victim_version_id)
    attacker = ingest_text(
        client, title="Сторонній наказ", text="Стороннє положення без стосунку до журналу."
    )
    approve(client, attacker["version"]["id"])

    repository = client.app.state.repository
    with privileged_connection(client) as connection:
        connection.execute(
            text(
                "UPDATE document_versions SET supersedes_version_id = :victim WHERE id = :attacker"
            ),
            {"victim": victim_version_id, "attacker": attacker["version"]["id"]},
        )

    rows = repository.list_retrievable_spans(
        admin_identity, frozenset({"public"}), date(2026, 8, 4)
    )

    assert any(str(version.id) == victim_version_id for _span, _document, version in rows), (
        "a supersession edge that crosses documents must be ignored by the projection, "
        "not merely refused at ingest"
    )
