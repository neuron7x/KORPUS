"""Four rules that lived in prose, in a discarded field, or in an untyped refusal.

- ADVERSARY was not a class the code knew: hostile or captured material could only be
  filed as something else, and the rule "an adversary source is never normative" sat in
  docs/governance/DATA_GOVERNANCE.md where nothing executed it.
- Approval could not carry an access tier. The tier that stood was whatever the
  uploader filed, and the approver — the person taking responsibility — had no say.
- The refusal for an unheld corpus was a sentence. Which corpus was refused, and in
  what order the reader asked, were both lost.
- Deduplication keyed on bytes alone: a re-issue under a new revision returned the
  existing version and silently dropped its dates and supersession edge.

`adversary-never-governs`, `explicit-tier-must-be-applied-on-approve`,
`any-unheld-corpus-denies-whole-request` and `revision-splits-version-not-document` in
docs/audit/INVARIANT_DIFF_2026-08-03.md.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from korpus.domain.models import AccessTier, AuthorityClass, Identity

from apps.api.tests.conftest import set_identity
from apps.api.tests.helpers import approve, ingest_text, transition

MARKER = "ТРОФЕЙНИЙ"


def test_only_normative_classes_may_govern_an_answer() -> None:
    assert AuthorityClass.OFFICIAL_UA.is_normative
    assert AuthorityClass.HISTORICAL.is_normative
    assert not AuthorityClass.ADVERSARY.is_normative, (
        "captured material may be held and shown, never treated as governing"
    )
    assert not AuthorityClass.UNKNOWN.is_normative


def test_an_adversary_source_cannot_be_approved(client: TestClient) -> None:
    result = ingest_text(
        client,
        title="Трофейний документ противника",
        authority="adversary",
        text=f"Маркер {MARKER} походить із документа противника.",
    )
    transition(client, result["version"]["id"], "metadata_reviewed")
    transition(client, result["version"]["id"], "content_reviewed")

    refusal = client.post(
        f"/v1/document-versions/{result['version']['id']}/review",
        json={"target": "approved", "note": "attempting to approve captured material"},
    )

    assert refusal.status_code == 409, refusal.text
    assert "adversary" in refusal.json()["detail"]


def test_an_adversary_source_never_reaches_an_answer(client: TestClient) -> None:
    """Even if a row reaches the eligible set, the class is not answerable."""
    result = ingest_text(
        client,
        title="Трофейний документ противника",
        authority="adversary",
        text=f"Маркер {MARKER} походить із документа противника.",
    )
    transition(client, result["version"]["id"], "metadata_reviewed")

    answer = client.post("/v1/answers", json={"text": f"що каже {MARKER}"}).json()

    assert answer["status"] == "insufficient_evidence"
    assert answer["citations"] == []


def test_the_approver_sets_the_access_tier(client: TestClient, admin_identity: Identity) -> None:
    result = ingest_text(client, title="Наказ для підняття тиру", access_tier=0)
    version_id = result["version"]["id"]
    transition(client, version_id, "metadata_reviewed")
    transition(client, version_id, "content_reviewed")

    response = client.post(
        f"/v1/document-versions/{version_id}/review",
        json={
            "target": "approved",
            "note": "approved and restricted by the approving officer",
            "access_tier": int(AccessTier.REVIEWED),
        },
    )

    assert response.status_code == 200, response.text
    documents = client.get("/v1/documents").json()
    stored = next(item for item in documents if item["id"] == result["document"]["id"])
    assert stored["access_tier"] == int(AccessTier.REVIEWED), (
        "the tier the approver decided on must be the tier the document carries"
    )


def test_an_approver_cannot_assign_a_tier_above_their_own_clearance(
    client: TestClient, authenticated_identity: Identity
) -> None:
    result = ingest_text(client, title="Наказ для підняття тиру", access_tier=0)
    version_id = result["version"]["id"]
    transition(client, version_id, "metadata_reviewed")
    transition(client, version_id, "content_reviewed")
    set_identity(
        client,
        authenticated_identity.model_copy(
            update={"roles": frozenset({"reviewer", "user"})}, deep=True
        ),
    )

    refusal = client.post(
        f"/v1/document-versions/{version_id}/review",
        json={
            "target": "approved",
            "note": "assigning a tier the approver cannot read",
            "access_tier": int(AccessTier.RESTRICTED),
        },
    )

    assert refusal.status_code == 403, refusal.text


def test_a_tier_may_only_be_set_on_approval(client: TestClient) -> None:
    result = ingest_text(client, title="Наказ для підняття тиру")

    refusal = client.post(
        f"/v1/document-versions/{result['version']['id']}/review",
        json={
            "target": "metadata_reviewed",
            "note": "metadata review is not where the tier is decided",
            "access_tier": 2,
        },
    )

    assert refusal.status_code == 422, refusal.text


def test_an_unheld_corpus_denies_the_request_and_names_which(
    client: TestClient, authenticated_identity: Identity
) -> None:
    set_identity(client, authenticated_identity)

    refusal = client.post(
        "/v1/answers",
        json={"text": "будь-яке питання", "corpus_ids": ["training", "restricted-demo"]},
    )

    assert refusal.status_code == 403
    detail = refusal.json()["detail"]
    assert detail["reason"] == "requested_corpora_not_held"
    assert detail["denied_corpora"] == ["restricted-demo"], (
        "the reader must learn which corpus was refused, not merely that one was"
    )
    assert detail["requested_corpora"] == ["training", "restricted-demo"], (
        "and in the order they asked — a frozenset loses it"
    )


def test_the_same_bytes_under_a_new_revision_are_a_new_version(client: TestClient) -> None:
    """A re-issue is a new state of the document, not an upload of what is already held."""
    body = "Порядок дій не змінився з попередньої редакції, змінилися лише строки."
    first = ingest_text(client, title="Наказ із незмінним текстом", revision="1.0", text=body)

    response = client.post(
        f"/v1/documents/{first['document']['id']}/versions/ingest",
        data={"version_json": json.dumps({"revision": "2.0", "authority": "official_ua"})},
        files={"file": ("v2.txt", body.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 201, response.text
    second = response.json()
    assert second["duplicate"] is False, (
        "identical bytes under revision 2.0 are a distinct version; deduplicating them "
        "discards the revision, its effective dates and its supersession edge"
    )
    assert second["version"]["id"] != first["version"]["id"]
    assert second["version"]["revision"] == "2.0"


def test_the_same_bytes_under_the_same_revision_are_still_a_duplicate(
    client: TestClient,
) -> None:
    body = "Порядок дій не змінився з попередньої редакції, змінилися лише строки."
    first = ingest_text(client, title="Наказ із незмінним текстом", revision="1.0", text=body)

    response = client.post(
        f"/v1/documents/{first['document']['id']}/versions/ingest",
        data={"version_json": json.dumps({"revision": "1.0", "authority": "official_ua"})},
        files={"file": ("again.txt", body.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["duplicate"] is True
    assert response.json()["version"]["id"] == first["version"]["id"]


def test_approved_documents_still_answer_after_the_governance_changes(
    client: TestClient,
) -> None:
    result = ingest_text(client, text=f"Маркер {MARKER} у затвердженому наказі підрозділу.")
    approve(client, result["version"]["id"])

    answer = client.post("/v1/answers", json={"text": f"де згадано {MARKER}"}).json()

    assert answer["status"] == "answered", answer["decision_reason"]
