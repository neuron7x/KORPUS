"""Token assurance is a policy the verifier must be able to fail.

`OIDCVerifier` pins algorithms, refuses plaintext endpoints, and — where a controlled
deployment asks for it — requires a recent authentication, a specific `acr`, and a
multi-factor `amr`. Those assurance branches were never taken by any test: the policy
existed as configuration options nothing had ever exercised, which is the state where
"MFA required" and "MFA field ignored" produce identical evidence.

The algorithm pin is the one worth stating explicitly. A verifier that accepts `none`
or a symmetric algorithm turns the JWKS into decoration, and the failure is silent —
tokens verify, they just verify against something the attacker chose.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from korpus.security.oidc import OIDCVerifier

JWKS_URL = "https://id.example/jwks"
ISSUER = "https://id.example"
AUDIENCE = "korpus"


def _verifier(**overrides: Any) -> OIDCVerifier:
    values: dict[str, Any] = {
        "jwks_url": JWKS_URL,
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "algorithms": ["RS256"],
        "client": object(),
    }
    values.update(overrides)
    return OIDCVerifier(**values)


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"jwks_url": "http://id.example/jwks"}, "JWKS URL must use HTTPS"),
        ({"issuer": "http://id.example"}, "issuer must use HTTPS"),
        ({"algorithms": []}, "explicitly pinned"),
        ({"algorithms": ["none"]}, "explicitly pinned"),
        ({"algorithms": ["HS256"]}, "explicitly pinned"),
        ({"algorithms": ["RS256", "RS256"]}, "explicitly pinned"),
        ({"algorithms": ["RS256", "HS256"]}, "explicitly pinned"),
        ({"max_auth_age_seconds": 30}, "too small"),
    ],
)
def test_a_verifier_that_could_not_verify_anything_is_refused_at_construction(
    overrides: dict[str, Any], reason: str
) -> None:
    with pytest.raises(ValueError, match=reason):
        _verifier(**overrides)


def test_a_usable_verifier_is_accepted() -> None:
    """The dual: the refusals above must not be refusing everything."""
    verifier = _verifier(algorithms=["RS256", "ES256"])

    assert verifier.algorithms == ("RS256", "ES256")
    assert verifier.issuer == ISSUER


def _claims(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": "analyst",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "auth_time": (now - timedelta(minutes=1)).timestamp(),
        "acr": "urn:acr:mfa",
        "amr": ["otp"],
    }
    claims.update(overrides)
    return claims


def test_a_recent_multifactor_authentication_satisfies_the_policy() -> None:
    """The dual for the assurance half."""
    _verifier(required_acr="urn:acr:mfa", require_mfa=True)._validate_assurance(_claims())


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"auth_time": None}, "auth_time claim is invalid"),
        ({"auth_time": "yesterday"}, "auth_time claim is invalid"),
        ({}, "auth_time claim is invalid"),
    ],
)
def test_an_unreadable_auth_time_is_refused(overrides: dict[str, Any], reason: str) -> None:
    claims = _claims(**overrides)
    if not overrides:
        claims.pop("auth_time")

    with pytest.raises(jwt.InvalidTokenError, match=reason):
        _verifier()._validate_assurance(claims)


def test_an_authentication_older_than_policy_is_refused() -> None:
    """A session from last week is not a fresh authentication for a controlled action."""
    stale = datetime.now(UTC) - timedelta(days=7)

    with pytest.raises(jwt.InvalidTokenError, match="authentication age exceeds policy"):
        _verifier()._validate_assurance(_claims(auth_time=stale.timestamp()))


def test_an_authentication_from_the_future_is_refused() -> None:
    """Beyond clock skew, a future auth_time is a clock nobody should trust."""
    ahead = datetime.now(UTC) + timedelta(hours=1)

    with pytest.raises(jwt.InvalidTokenError, match="authentication age exceeds policy"):
        _verifier()._validate_assurance(_claims(auth_time=ahead.timestamp()))


def test_a_missing_acr_is_refused_when_one_is_required() -> None:
    with pytest.raises(jwt.InvalidTokenError, match="acr does not satisfy policy"):
        _verifier(required_acr="urn:acr:mfa")._validate_assurance(_claims(acr="urn:acr:password"))


def test_a_single_factor_authentication_is_refused_when_mfa_is_required() -> None:
    with pytest.raises(jwt.InvalidTokenError, match="MFA authentication method is required"):
        _verifier(require_mfa=True)._validate_assurance(_claims(amr=["pwd"]))


@pytest.mark.parametrize("amr", ["otp", "OTP", ["pwd", "webauthn"], ["FIDO"]])
def test_any_recognised_second_factor_satisfies_the_requirement(amr: Any) -> None:
    """`amr` is a string or a list, and case is the IdP's choice, not a policy."""
    _verifier(require_mfa=True)._validate_assurance(_claims(amr=amr))


def test_an_empty_amr_is_refused_rather_than_ignored() -> None:
    with pytest.raises(jwt.InvalidTokenError, match="MFA authentication method is required"):
        _verifier(require_mfa=True)._validate_assurance(_claims(amr=[]))
