from __future__ import annotations

import itertools

from korpus.application.ingestion import ALLOWED_TRANSITIONS
from korpus.domain.models import ReviewState


def test_review_state_machine_has_no_path_out_of_rejected():
    assert ALLOWED_TRANSITIONS[ReviewState.REJECTED] == frozenset()


def test_approval_is_reachable_only_through_both_review_stages():
    paths: list[tuple[ReviewState, ...]] = []
    for length in range(1, 6):
        for transitions in itertools.product(list(ReviewState), repeat=length):
            current = ReviewState.QUARANTINED
            valid = True
            visited = [current]
            for target in transitions:
                if target not in ALLOWED_TRANSITIONS[current]:
                    valid = False
                    break
                current = target
                visited.append(current)
            if valid and current is ReviewState.APPROVED:
                paths.append(tuple(visited))
    assert paths
    assert all(
        ReviewState.METADATA_REVIEWED in path and ReviewState.CONTENT_REVIEWED in path
        for path in paths
    )


def test_controlled_review_separation_is_subject_based(tmp_path):
    from fastapi.testclient import TestClient

    from korpus.config import Settings
    from korpus.domain.models import AccessTier, Identity
    from korpus.main import create_app
    from korpus.security.auth import get_identity

    from .helpers import ingest_text

    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'separation.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="test-audit-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        review_separation_required=True,
    )
    identities = {
        "curator-a": Identity(
            subject="curator-a",
            roles=frozenset({"curator"}),
            clearance=AccessTier.PUBLIC,
            corpora=frozenset({"public"}),
        ),
        "reviewer-a": Identity(
            subject="curator-a",
            roles=frozenset({"reviewer"}),
            clearance=AccessTier.PUBLIC,
            corpora=frozenset({"public"}),
        ),
        "reviewer-b": Identity(
            subject="reviewer-b",
            roles=frozenset({"reviewer"}),
            clearance=AccessTier.PUBLIC,
            corpora=frozenset({"public"}),
        ),
        "approver-c": Identity(
            subject="approver-c",
            roles=frozenset({"reviewer"}),
            clearance=AccessTier.PUBLIC,
            corpora=frozenset({"public"}),
        ),
    }
    current = [identities["curator-a"]]
    app = create_app(settings)
    app.dependency_overrides[get_identity] = lambda: current[0]
    with TestClient(app) as client:
        created = ingest_text(client)
        version_id = created["version"]["id"]
        metadata = client.post(
            f"/v1/document-versions/{version_id}/review",
            json={"target": "metadata_reviewed", "note": "metadata review complete"},
        )
        assert metadata.status_code == 200
        assert metadata.json()["metadata_reviewed_by"] == "curator-a"

        current[0] = identities["reviewer-a"]
        same_subject = client.post(
            f"/v1/document-versions/{version_id}/review",
            json={"target": "content_reviewed", "note": "content review attempted"},
        )
        assert same_subject.status_code == 409
        assert "differ" in same_subject.json()["detail"]

        current[0] = identities["reviewer-b"]
        content = client.post(
            f"/v1/document-versions/{version_id}/review",
            json={"target": "content_reviewed", "note": "content review complete"},
        )
        assert content.status_code == 200
        assert content.json()["content_reviewed_by"] == "reviewer-b"

        same_approver = client.post(
            f"/v1/document-versions/{version_id}/review",
            json={"target": "approved", "note": "approval attempted"},
        )
        assert same_approver.status_code == 409
        assert "differ" in same_approver.json()["detail"]

        current[0] = identities["approver-c"]
        approved = client.post(
            f"/v1/document-versions/{version_id}/review",
            json={"target": "approved", "note": "independent approval complete"},
        )
        assert approved.status_code == 200
        body = approved.json()
        assert body["approved_by"] == "approver-c"
        assert len({body["metadata_reviewed_by"], body["content_reviewed_by"], body["approved_by"]}) == 3
