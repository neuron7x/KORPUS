"""An order cannot be in force before it exists.

Destruction stage, MAJOR: `effective_from = NULL` gave a version no lower bound at all,
so a document approved today was cited as governing on 1900-01-01 — and, being the only
current version, it answered "which rules applied on that date" with itself. The upper
bound (`effective_until`) was named and defended on 2026-08-03; the lower one was not
even present.

For the question this system exists to answer — did this order govern on date X — an
open lower bound is not a missing feature. It is a wrong answer delivered with a
citation.

The rule stated here: an approved version must say when it started to govern, either
through `effective_from` or through `publication_date`. Both absent is refused at the
approval transition rather than silently treated as "always".
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from apps.api.tests.helpers import approve, ingest_text, transition

MARKER = "МЕЖА"
BODY = f"Порядок {MARKER} встановлює добовий облік у підрозділі."


def test_an_approved_order_does_not_govern_before_it_took_effect(
    client: TestClient,
) -> None:
    result = ingest_text(client, text=BODY, effective_from=date(2026, 6, 1))
    approve(client, result["version"]["id"])

    before = client.post(
        "/v1/answers", json={"text": f"який порядок {MARKER}", "as_of": "2026-05-31"}
    ).json()
    on_the_day = client.post(
        "/v1/answers", json={"text": f"який порядок {MARKER}", "as_of": "2026-06-01"}
    ).json()

    assert before["status"] == "insufficient_evidence", before["decision_reason"]
    assert on_the_day["status"] == "answered", on_the_day["decision_reason"]


def test_publication_date_serves_as_the_lower_bound_when_effective_from_is_absent(
    client: TestClient,
) -> None:
    """Many orders state a date of issue and no separate commencement date."""
    result = ingest_text(client, text=BODY, publication_date=date(2026, 6, 1))
    approve(client, result["version"]["id"])

    before = client.post(
        "/v1/answers", json={"text": f"який порядок {MARKER}", "as_of": "2026-05-31"}
    ).json()

    assert before["status"] == "insufficient_evidence", before["decision_reason"]


def test_a_version_with_no_lower_bound_at_all_cannot_be_approved(
    client: TestClient,
) -> None:
    """Refused at the transition, not treated as governing since 1900."""
    result = ingest_text(client, text=BODY, publication_date=None)
    version_id = result["version"]["id"]
    transition(client, version_id, "metadata_reviewed")
    transition(client, version_id, "content_reviewed")

    response = client.post(
        f"/v1/document-versions/{version_id}/review",
        json={"target": "approved", "note": "independent verification completed for approval"},
    )

    assert response.status_code in {400, 409, 422}, response.text
    assert "effective_from" in response.text or "publication_date" in response.text


def test_the_projection_ignores_an_unbounded_version_already_in_the_database(
    client: TestClient,
) -> None:
    """The second line, where the approval check can no longer reach.

    With approval refusing an unbounded version, the SQL filter guards a state the API
    cannot produce. The row is written directly, which is what a bulk import or a
    migration from an older schema leaves behind.
    """
    from datetime import date as date_type

    from sqlalchemy import text as sql

    result = ingest_text(client, text=BODY, effective_from=date(2026, 6, 1))
    version_id = result["version"]["id"]
    approve(client, version_id)
    repository = client.app.state.repository
    with repository.engine.begin() as connection:
        connection.execute(
            sql(
                "UPDATE document_versions SET effective_from = NULL, publication_date = NULL "
                "WHERE id = :id"
            ),
            {"id": version_id},
        )

    rows = repository.list_retrievable_spans(
        client.identity_provider.current,  # type: ignore[attr-defined]
        frozenset({"public"}),
        date_type(1900, 1, 1),
    )

    assert all(str(version.id) != version_id for _span, _document, version in rows), (
        "a version with no lower bound must not be retrievable on an arbitrary past date"
    )


def test_the_candidate_sql_excludes_an_unbounded_version(client: TestClient) -> None:
    """Stated against the SQL layer, which the domain check would otherwise mask.

    `list_retrievable_spans` filters twice: once in the candidate query and once in
    `is_valid_on` while materialising. Weakening either one alone changes nothing
    observable, so a mutation of the SQL bound survives every behavioural test. The
    candidate query is therefore asked directly.
    """
    from datetime import date as date_type

    from sqlalchemy import text as sql

    result = ingest_text(client, text=BODY, effective_from=date(2026, 6, 1))
    version_id = result["version"]["id"]
    approve(client, version_id)
    repository = client.app.state.repository
    with repository.engine.begin() as connection:
        connection.execute(
            sql(
                "UPDATE document_versions SET effective_from = NULL, publication_date = NULL "
                "WHERE id = :id"
            ),
            {"id": version_id},
        )

    candidates = repository._candidate_span_ids(
        client.identity_provider.current,  # type: ignore[attr-defined]
        frozenset({"public"}),
        date_type(1900, 1, 1),
        MARKER,
        50,
    )

    assert candidates == [], (
        "the candidate query must exclude a version with no lower bound, independently "
        "of the domain check that runs after it"
    )
