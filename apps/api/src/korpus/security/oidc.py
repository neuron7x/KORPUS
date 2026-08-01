from __future__ import annotations

from datetime import UTC, datetime
import secrets
from typing import Any

import jwt


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
        if not jwks_url.startswith("https://"):
            raise ValueError("OIDC JWKS URL must use HTTPS")
        if not issuer.startswith("https://"):
            raise ValueError("OIDC issuer must use HTTPS")
        allowed_algorithms = {
            "RS256",
            "RS384",
            "RS512",
            "PS256",
            "PS384",
            "PS512",
            "ES256",
            "ES384",
            "ES512",
            "EdDSA",
        }
        if (
            not algorithms
            or len(set(algorithms)) != len(algorithms)
            or any(algorithm not in allowed_algorithms for algorithm in algorithms)
        ):
            raise ValueError("OIDC algorithms must be asymmetric, supported, unique, and explicitly pinned")
        if max_auth_age_seconds < 60:
            raise ValueError("max_auth_age_seconds is too small")
        self.issuer = issuer
        self.audience = audience
        self.algorithms = tuple(algorithms)
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
        require_auth_time: bool = True,
    ) -> dict[str, Any]:
        header = jwt.get_unverified_header(token)
        algorithm = str(header.get("alg", ""))
        key_id = str(header.get("kid", ""))
        if algorithm not in self.algorithms:
            raise jwt.InvalidAlgorithmError("token algorithm is not allowed")
        if not key_id:
            raise jwt.InvalidTokenError("token kid is required for rotation-safe verification")
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
                    "sub", "exp", "iat", "nbf", "iss", "aud", "jti",
                    *(["auth_time"] if require_auth_time else []),
                ]
            },
        )
        if not isinstance(claims.get("aud"), (str, list)):
            raise jwt.InvalidAudienceError("aud claim has invalid type")
        if expected_nonce is not None:
            nonce = claims.get("nonce")
            if not isinstance(nonce, str) or not secrets.compare_digest(nonce, expected_nonce):
                raise jwt.InvalidTokenError("OIDC nonce mismatch")
        if require_auth_time:
            self._validate_assurance(claims)
        return claims

    def _validate_assurance(self, claims: dict[str, Any]) -> None:
        try:
            auth_time = datetime.fromtimestamp(float(claims["auth_time"]), tz=UTC)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise jwt.InvalidTokenError("auth_time claim is invalid") from exc
        age = (datetime.now(UTC) - auth_time).total_seconds()
        if age < -self.clock_skew_seconds or age > self.max_auth_age_seconds + self.clock_skew_seconds:
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
