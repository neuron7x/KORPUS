from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import jwt

from korpus.security.external_destination import parse_external_https_url
from korpus.security.oidc_claims import (
    validate_algorithms,
    validate_audience_and_authorized_party,
    validate_header,
    validate_nonce,
)
from korpus.security.oidc_numeric import numeric_date, validate_oidc_timing
from korpus.security.url_policy import parse_https_url


class OIDCVerifier:
    """Long-lived OIDC verifier with bounded JWKS caching and assurance checks."""

    def __init__(
        self,
        *,
        jwks_url: str,
        issuer: str,
        audience: str,
        algorithms: list[str],
        jwks_cache_seconds: int = 300,
        http_timeout_seconds: float = 5.0,
        clock_skew_seconds: int = 30,
        required_acr: str | None = None,
        require_mfa: bool = False,
        max_auth_age_seconds: int = 3600,
        client: Any | None = None,
    ) -> None:
        parse_external_https_url(jwks_url, name="OIDC JWKS URL")
        parse_https_url(issuer, name="OIDC issuer", allow_query=False)
        pinned_algorithms = validate_algorithms(algorithms)
        jwks_cache_seconds, http_timeout_seconds, clock_skew_seconds, max_auth_age_seconds = (
            validate_oidc_timing(
                jwks_cache_seconds, http_timeout_seconds, clock_skew_seconds, max_auth_age_seconds
            )
        )
        self.issuer = issuer
        self.audience = audience
        self.algorithms = pinned_algorithms
        self.clock_skew_seconds = clock_skew_seconds
        self.required_acr = required_acr
        self.require_mfa = require_mfa
        self.max_auth_age_seconds = max_auth_age_seconds
        self.client = client or jwt.PyJWKClient(
            jwks_url,
            cache_keys=True,
            max_cached_keys=16,
            cache_jwk_set=True,
            lifespan=float(jwks_cache_seconds),
            timeout=http_timeout_seconds,
        )

    def verify(
        self,
        token: str,
        *,
        audience: str | None = None,
        expected_nonce: str | None = None,
        authorized_party: str | None = None,
        require_auth_time: bool = True,
    ) -> dict[str, Any]:
        validate_header(token, self.algorithms)
        signing_key = self.client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=list(self.algorithms),
            audience=audience or self.audience,
            issuer=self.issuer,
            leeway=self.clock_skew_seconds,
            options={
                "require": [
                    "sub",
                    "exp",
                    "iat",
                    "nbf",
                    "iss",
                    "aud",
                    "jti",
                    *(["auth_time"] if require_auth_time else []),
                ]
            },
        )
        validate_audience_and_authorized_party(claims, authorized_party)
        validate_nonce(claims, expected_nonce)
        if require_auth_time:
            self._validate_assurance(claims)
        return claims

    def _validate_assurance(self, claims: dict[str, Any]) -> None:
        try:
            auth_time = numeric_date(claims["auth_time"], claim="auth_time")
        except (KeyError, TypeError, ValueError, OSError, OverflowError) as exc:
            raise jwt.InvalidTokenError("auth_time claim is invalid") from exc
        age = (datetime.now(UTC) - auth_time).total_seconds()
        if (
            age < -self.clock_skew_seconds
            or age > self.max_auth_age_seconds + self.clock_skew_seconds
        ):
            raise jwt.InvalidTokenError("authentication age exceeds policy")
        if self.required_acr is not None and claims.get("acr") != self.required_acr:
            raise jwt.InvalidTokenError("acr does not satisfy policy")
        if self.require_mfa:
            amr = claims.get("amr", [])
            methods = {str(value).lower() for value in ([amr] if isinstance(amr, str) else amr)}
            if not methods.intersection({"mfa", "otp", "hwk", "swk", "fido", "webauthn"}):
                raise jwt.InvalidTokenError("MFA authentication method is required")

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
