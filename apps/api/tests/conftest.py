from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.main import create_app


@pytest.fixture
def admin_identity() -> Identity:
    return Identity(
        subject="admin-test",
        roles=frozenset({"admin", "curator", "reviewer", "user", "auditor"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public", "restricted-demo"}),
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
def client(tmp_path: Path, admin_identity: Identity) -> Iterator[TestClient]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        object_root=tmp_path / "objects",
        audit_hmac_key="test-audit-key",
        auth_mode="dev",
        min_retrieval_score=0.10,
        min_query_coverage=0.20,
    )
    app = create_app(settings)
    app.state.identity_override = admin_identity
    with TestClient(app) as test_client:
        yield test_client
    app.state.repository.engine.dispose()
