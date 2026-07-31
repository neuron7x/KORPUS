from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from korpus.security.oidc import OIDCVerifier


class FakeJWKClient:
    def __init__(self, key):
        self.key = key
        self.calls = 0

    def get_signing_key_from_jwt(self, token):
        self.calls += 1
        return SimpleNamespace(key=self.key.public_key())


def token(private_key, *, alg="RS256", kid="k1", issuer="https://id.example"):
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "user-1",
            "iss": issuer,
            "aud": "korpus-api",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm=alg,
        headers={"kid": kid} if kid else {},
    )


def test_oidc_verifier_pins_algorithm_issuer_audience_and_kid():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = FakeJWKClient(key)
    verifier = OIDCVerifier(
        jwks_url="https://id.example/jwks",
        issuer="https://id.example",
        audience="korpus-api",
        algorithms=["RS256"],
        client=client,
    )
    assert verifier.verify(token(key))["sub"] == "user-1"
    with pytest.raises(jwt.InvalidTokenError):
        verifier.verify(token(key, kid=""))
    with pytest.raises(jwt.InvalidIssuerError):
        verifier.verify(token(key, issuer="https://evil.example"))


def test_oidc_rejects_symmetric_or_insecure_configuration():
    with pytest.raises(ValueError):
        OIDCVerifier(
            jwks_url="http://id.example/jwks",
            issuer="https://id.example",
            audience="api",
            algorithms=["RS256"],
        )
    with pytest.raises(ValueError):
        OIDCVerifier(
            jwks_url="https://id.example/jwks",
            issuer="https://id.example",
            audience="api",
            algorithms=["HS256"],
        )
