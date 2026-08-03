from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.main import create_app
from korpus.security.auth import get_identity


class IdentityProvider:
    def __init__(self, identity: Identity) -> None:
        self.current = identity

    def __call__(self) -> Identity:
        return self.current


@pytest.fixture
def admin_identity() -> Identity:
    return Identity(
        subject="admin-test",
        roles=frozenset({"admin", "curator", "reviewer", "user", "auditor"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public", "training", "restricted-demo"}),
    )


@pytest.fixture
def public_identity() -> Identity:
    return Identity(
        subject="public-test",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )


@pytest.fixture
def authenticated_identity() -> Identity:
    return Identity(
        subject="authenticated-test",
        roles=frozenset({"user"}),
        clearance=AccessTier.AUTHENTICATED,
        corpora=frozenset({"public", "training"}),
    )


@pytest.fixture
def client(tmp_path: Path, admin_identity: Identity) -> Iterator[TestClient]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "audit-anchor.json",
        audit_hmac_key="test-audit-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        min_retrieval_score=0.08,
        min_query_coverage=0.15,
        min_support_score=0.08,
        max_upload_bytes=1024 * 1024,
    )
    app = create_app(settings)
    provider = IdentityProvider(admin_identity)
    app.dependency_overrides[get_identity] = provider
    with TestClient(app) as test_client:
        test_client.identity_provider = provider  # type: ignore[attr-defined]
        yield test_client


def set_identity(client: TestClient, identity: Identity) -> None:
    client.identity_provider.current = identity  # type: ignore[attr-defined]
