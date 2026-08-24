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
            "nbf": now - timedelta(seconds=1),
            "auth_time": int(now.timestamp()),
            "jti": "oidc-test-jti",
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


def test_oidc_rejects_symmetric_unknown_and_duplicate_algorithms():
    import pytest
    from korpus.security.oidc import OIDCVerifier

    for algorithms in (["HS256"], ["none"], ["RS256", "RS256"], ["CUSTOM"]):
        with pytest.raises(ValueError, match="asymmetric"):
            OIDCVerifier(
                jwks_url="https://id.example/jwks",
                issuer="https://id.example/",
                audience="korpus-api",
                algorithms=algorithms,
                client=object(),
            )


def test_oidc_rejects_credential_bearing_or_ambiguous_provider_urls():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for jwks_url, issuer in (
        ("https://user:secret@id.example/jwks", "https://id.example"),
        ("https://id.example/jwks#fragment", "https://id.example"),
        ("https://id.example/jwks", "https://id.example?tenant=alpha"),
        ("https://id.example:bad/jwks", "https://id.example"),
    ):
        with pytest.raises(ValueError):
            OIDCVerifier(
                jwks_url=jwks_url,
                issuer=issuer,
                audience="korpus-api",
                algorithms=["RS256"],
                client=FakeJWKClient(key),
            )


def test_oidc_multi_audience_requires_azp_and_rejects_wrong_authorized_party():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = FakeJWKClient(key)
    verifier = OIDCVerifier(
        jwks_url="https://id.example/jwks",
        issuer="https://id.example",
        audience="korpus-api",
        algorithms=["RS256"],
        client=client,
    )
    now = datetime.now(UTC)
    base = {
        "sub": "user-1",
        "iss": "https://id.example",
        "aud": ["korpus-api", "secondary-api"],
        "iat": now,
        "nbf": now - timedelta(seconds=1),
        "auth_time": int(now.timestamp()),
        "jti": "multi-aud-jti",
        "exp": now + timedelta(minutes=5),
    }
    missing_azp = jwt.encode(base, key, algorithm="RS256", headers={"kid": "k1"})
    with pytest.raises(jwt.InvalidTokenError, match="requires azp"):
        verifier.verify(missing_azp)

    valid = jwt.encode(
        {**base, "azp": "browser-client"},
        key,
        algorithm="RS256",
        headers={"kid": "k1"},
    )
    assert verifier.verify(valid, authorized_party="browser-client")["sub"] == "user-1"
    with pytest.raises(jwt.InvalidTokenError, match="authorized party"):
        verifier.verify(valid, authorized_party="other-client")


def test_oidc_rejects_unexpected_explicit_jwt_media_type():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = OIDCVerifier(
        jwks_url="https://id.example/jwks",
        issuer="https://id.example",
        audience="korpus-api",
        algorithms=["RS256"],
        client=FakeJWKClient(key),
    )
    now = datetime.now(UTC)
    payload = {
        "sub": "user-1",
        "iss": "https://id.example",
        "aud": "korpus-api",
        "iat": now,
        "nbf": now - timedelta(seconds=1),
        "auth_time": int(now.timestamp()),
        "jti": "bad-typ-jti",
        "exp": now + timedelta(minutes=5),
    }
    encoded = jwt.encode(
        payload,
        key,
        algorithm="RS256",
        headers={"kid": "k1", "typ": "JOSE"},
    )
    with pytest.raises(jwt.InvalidTokenError, match="typ"):
        verifier.verify(encoded)
