"""Local token issuance must be unavailable where it would be a back door.

`issue_token` mints a bearer token signed with a secret the deployment holds. In dev
and jwt modes that is the point; in oidc mode it would be a way to manufacture an
identity without the identity provider, and in disabled mode it would issue
credentials for an interface that refuses to authenticate anyone.

Both refusals, and the lifetime bound, were unexercised branches. A ceiling nothing
has ever hit is a ceiling that may not be there: `jwt_max_lifetime_minutes` exists so
a caller cannot ask for a year-long token, and until now no test had asked.
"""

from __future__ import annotations

from datetime import UTC, datetime

import jwt
import pytest
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.security.auth import issue_token

IDENTITY = Identity(
    subject="analyst",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public"}),
    compartments=frozenset(),
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "local",
        "database_url": "sqlite:///./var/korpus.db",
        "auth_mode": "jwt",
        "jwt_secret": "local-jwt-secret-for-tests-0123456789",
        "jwt_issuer": "https://id.example",
        "jwt_audience": "korpus",
    }
    values.update(overrides)
    return Settings(**values)


def test_a_token_issued_in_jwt_mode_carries_the_identity() -> None:
    """The dual: the refusals below must not be refusing every mode."""
    settings = _settings()

    token = issue_token(IDENTITY, settings, lifetime_minutes=5)
    claims = jwt.decode(
        token,
        settings.resolved_jwt_secret,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )

    assert claims["sub"] == "analyst"
    assert claims["roles"] == ["user"]
    assert claims["exp"] > datetime.now(UTC).timestamp()


def test_local_issuance_is_unavailable_in_oidc_mode() -> None:
    """Otherwise the deployment can mint the identities the IdP is there to attest."""
    settings = _settings(
        auth_mode="oidc",
        oidc_jwks_url="https://id.example/jwks",
        browser_auth_enabled=False,
    )

    with pytest.raises(ValueError, match="unavailable for this authentication mode"):
        issue_token(IDENTITY, settings)


def test_local_issuance_is_unavailable_when_authentication_is_disabled() -> None:
    settings = _settings(auth_mode="disabled")

    with pytest.raises(ValueError, match="unavailable for this authentication mode"):
        issue_token(IDENTITY, settings)


@pytest.mark.parametrize("lifetime", [0, -1, 10**6])
def test_a_lifetime_outside_the_configured_bound_is_refused(lifetime: int) -> None:
    """A ceiling nothing has ever hit is a ceiling that may not be there."""
    with pytest.raises(ValueError, match="lifetime exceeds configured maximum"):
        issue_token(IDENTITY, _settings(), lifetime_minutes=lifetime)


def test_the_bound_is_the_configured_one_rather_than_a_constant() -> None:
    settings = _settings(jwt_max_lifetime_minutes=15)

    issue_token(IDENTITY, settings, lifetime_minutes=15)
    with pytest.raises(ValueError, match="lifetime exceeds configured maximum"):
        issue_token(IDENTITY, settings, lifetime_minutes=16)
