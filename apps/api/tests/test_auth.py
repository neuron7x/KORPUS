from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.main import create_app
from korpus.security.auth import issue_token


def test_query_contract_has_no_client_controlled_clearance():
    from korpus.domain.models import QueryRequest

    assert "user_tier" not in QueryRequest.model_fields
    assert "clearance" not in QueryRequest.model_fields
    assert "roles" not in QueryRequest.model_fields


def test_signed_token_contains_server_verified_identity():
    settings = Settings(environment="test", auth_mode="jwt", jwt_secret="x" * 32)
    identity = Identity(
        subject="u-1",
        roles=frozenset({"user"}),
        clearance=AccessTier.AUTHENTICATED,
        corpora=frozenset({"public"}),
    )
    token = issue_token(identity, settings)
    claims = jwt.decode(
        token,
        settings.resolved_jwt_secret,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
    assert claims["sub"] == "u-1"
    assert claims["jti"]
    assert token.count(".") == 2


def test_controlled_environment_requires_oidc():
    with pytest.raises(ValueError, match="OIDC authentication"):
        Settings(environment="production", auth_mode="dev")


def test_local_jwt_rejects_weak_secret():
    with pytest.raises(ValueError, match="JWT secret"):
        Settings(environment="test", auth_mode="jwt", jwt_secret="weak")


def test_secret_files_are_resolved(tmp_path: Path):
    jwt_file = tmp_path / "jwt"
    audit_file = tmp_path / "audit"
    jwt_file.write_text("j" * 40)
    audit_file.write_text("a" * 40)
    settings = Settings(
        environment="test",
        auth_mode="jwt",
        jwt_secret_file=jwt_file,
        audit_hmac_key_file=audit_file,
    )
    assert settings.resolved_jwt_secret == "j" * 40
    assert settings.resolved_audit_hmac_key == "a" * 40


def test_jwt_auth_rejects_expired_wrong_audience_and_overlong_lifetime(tmp_path: Path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'jwt.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        auth_mode="jwt",
        jwt_secret="s" * 32,
        audit_hmac_key="audit-test",
        jwt_max_lifetime_minutes=60,
    )
    app = create_app(settings)
    now = datetime.now(UTC)
    base = {
        "sub": "jwt-user",
        "roles": ["user"],
        "clearance": "public",
        "corpora": ["public"],
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "nbf": now,
        "jti": "jti-1",
    }
    expired = jwt.encode({**base, "exp": now - timedelta(seconds=1)}, settings.jwt_secret, algorithm="HS256")
    wrong_aud = jwt.encode({**base, "aud": "wrong", "exp": now + timedelta(minutes=5)}, settings.jwt_secret, algorithm="HS256")
    overlong = jwt.encode({**base, "exp": now + timedelta(minutes=61)}, settings.jwt_secret, algorithm="HS256")
    valid = jwt.encode({**base, "exp": now + timedelta(minutes=5)}, settings.jwt_secret, algorithm="HS256")
    with TestClient(app) as api:
        for token in (expired, wrong_aud, overlong):
            assert api.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
        assert api.get("/v1/auth/me", headers={"Authorization": f"Bearer {valid}"}).status_code == 200


def test_controlled_environment_requires_migration_managed_schema():
    with pytest.raises(ValueError, match="migration-managed schema"):
        Settings(
            environment="production",
            auth_mode="oidc",
            oidc_jwks_url="https://id.example/jwks",
            audit_hmac_key="a" * 40,
        )
