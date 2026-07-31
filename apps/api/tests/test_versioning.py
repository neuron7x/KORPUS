from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date


from apps.api.tests.helpers import approve, ingest_text, ingest_version, transition
from korpus.domain.models import ReviewState
from korpus.infrastructure.repository import ConcurrentWriteError


def test_new_approved_version_supersedes_old_version_in_current_retrieval(client):
    first = ingest_text(
        client,
        text="OLD-MARKER журнал містить старий порядок перевірки.",
        effective_from=date(2025, 1, 1),
    )
    approve(client, first["version"]["id"])
    second = ingest_version(
        client,
        first["document"]["id"],
        revision="2.0",
        text="NEW-MARKER журнал використовує чинний порядок перевірки.",
        supersedes_version_id=first["version"]["id"],
        effective_from=date(2026, 1, 1),
    )
    approve(client, second["version"]["id"])

    old_current = client.post("/v1/answers", json={"text": "OLD-MARKER", "as_of": "2026-07-31"}).json()
    new_current = client.post(
        "/v1/answers",
        json={"text": "NEW-MARKER чинний порядок", "as_of": "2026-07-31"},
    ).json()
    old_historical = client.post(
        "/v1/answers",
        json={"text": "OLD-MARKER старий порядок", "as_of": "2025-07-31"},
    ).json()
    assert old_current["status"] == "insufficient_evidence"
    assert new_current["status"] == "answered"
    assert old_historical["status"] == "answered"
    assert all(citation["version_id"] == second["version"]["id"] for citation in new_current["citations"])


def test_competing_branch_cannot_be_approved(client):
    first = ingest_text(client, text="BASE-MARKER baseline.")
    approve(client, first["version"]["id"])
    second = ingest_version(
        client,
        first["document"]["id"],
        revision="2",
        text="SECOND-MARKER replacement.",
        supersedes_version_id=first["version"]["id"],
    )
    approve(client, second["version"]["id"])
    branch = ingest_version(
        client,
        first["document"]["id"],
        revision="2-branch",
        text="BRANCH-MARKER conflicting replacement.",
        supersedes_version_id=first["version"]["id"],
    )
    transition(client, branch["version"]["id"], "metadata_reviewed")
    transition(client, branch["version"]["id"], "content_reviewed")
    response = client.post(
        f"/v1/document-versions/{branch['version']['id']}/review",
        json={"target": "approved", "note": "independent approval of a conflicting branch attempted"},
    )
    assert response.status_code == 409
    assert "current approved" in response.text


def test_supersedes_must_reference_same_document(client):
    first = ingest_text(client, title="One", text="Document one unique content.")
    second = ingest_text(client, title="Two", text="Document two unique content.")
    import json

    response = client.post(
        f"/v1/documents/{second['document']['id']}/versions/ingest",
        data={
            "version_json": json.dumps(
                {
                    "revision": "2",
                    "authority": "official_ua",
                    "supersedes_version_id": first["version"]["id"],
                }
            )
        },
        files={"file": ("v2.txt", b"Third unique version content.", "text/plain")},
    )
    assert response.status_code == 422


def test_optimistic_state_transition_kills_double_approval(client, admin_identity):
    result = ingest_text(client, text="CONCURRENT-APPROVAL-MARKER")
    transition(client, result["version"]["id"], "metadata_reviewed")
    transition(client, result["version"]["id"], "content_reviewed")
    repository = client.app.state.repository
    version_id = result["version"]["id"]

    def approve_direct():
        return repository.transition_version(
            admin_identity,
            __import__("uuid").UUID(version_id),
            ReviewState.CONTENT_REVIEWED,
            ReviewState.APPROVED,
            "independent concurrent approval transition verification",
        )

    outcomes: list[str] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(approve_direct) for _ in range(2)]
        for future in futures:
            try:
                future.result()
                outcomes.append("approved")
            except ConcurrentWriteError:
                outcomes.append("conflict")
    assert sorted(outcomes) == ["approved", "conflict"]
