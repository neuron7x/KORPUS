from pathlib import Path

from fastapi.testclient import TestClient

from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.main import create_app
from korpus.security.auth import issue_token


def test_jwt_auth_accepts_valid_token_and_rejects_invalid(tmp_path: Path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'jwt.db'}",
        object_root=tmp_path / "objects",
        auth_mode="jwt",
        jwt_secret="s" * 32,
        audit_hmac_key="audit-test",
    )
    app = create_app(settings)
    identity = Identity(
        subject="jwt-user",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )
    with TestClient(app) as client:
        assert client.get("/v1/auth/me").status_code == 401
        assert client.get("/v1/auth/me", headers={"Authorization": "Bearer invalid"}).status_code == 401
        token = issue_token(identity, settings)
        response = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["subject"] == "jwt-user"
    app.state.repository.engine.dispose()
