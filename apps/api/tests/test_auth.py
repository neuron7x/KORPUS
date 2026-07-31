import pytest

from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.security.auth import issue_token


def test_query_contract_has_no_user_tier():
    from korpus.domain.models import QueryRequest

    assert "user_tier" not in QueryRequest.model_fields
    assert "clearance" not in QueryRequest.model_fields


def test_signed_token_contains_server_verified_identity():
    settings = Settings(environment="test", auth_mode="jwt", jwt_secret="x" * 32)
    identity = Identity(
        subject="u-1",
        roles=frozenset({"user"}),
        clearance=AccessTier.AUTHENTICATED,
        corpora=frozenset({"public"}),
    )
    token = issue_token(identity, settings)
    assert isinstance(token, str)
    assert token.count(".") == 2


def test_production_rejects_dev_auth():
    with pytest.raises(ValueError, match="dev authentication"):
        Settings(environment="production", auth_mode="dev")


def test_production_rejects_weak_default_secrets():
    import pytest

    with pytest.raises(ValueError, match="JWT secret"):
        Settings(
            environment="production",
            auth_mode="jwt",
            jwt_secret="replace-local-jwt-secret",
            audit_hmac_key="a" * 40,
        )


def test_secret_files_are_resolved(tmp_path):
    jwt_file = tmp_path / "jwt"
    audit_file = tmp_path / "audit"
    jwt_file.write_text("j" * 40)
    audit_file.write_text("a" * 40)
    settings = Settings(
        environment="production",
        auth_mode="jwt",
        jwt_secret_file=jwt_file,
        audit_hmac_key_file=audit_file,
    )
    assert settings.resolved_jwt_secret == "j" * 40
    assert settings.resolved_audit_hmac_key == "a" * 40
