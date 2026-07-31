from __future__ import annotations

from typing import Any

import jwt


class OIDCVerifier:
    """Long-lived OIDC verifier with bounded JWKS caching and algorithm pinning."""

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
        client: Any | None = None,
    ) -> None:
        if not jwks_url.startswith("https://"):
            raise ValueError("OIDC JWKS URL must use HTTPS")
        if not issuer.startswith("https://"):
            raise ValueError("OIDC issuer must use HTTPS")
        if not algorithms or any(algorithm.startswith("HS") or algorithm == "none" for algorithm in algorithms):
            raise ValueError("OIDC algorithms must be asymmetric and explicitly pinned")
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.algorithms = tuple(algorithms)
        self.clock_skew_seconds = clock_skew_seconds
        self.client = client or jwt.PyJWKClient(
            jwks_url,
            cache_keys=True,
            max_cached_keys=16,
            cache_jwk_set=True,
            lifespan=float(jwks_cache_seconds),
            timeout=http_timeout_seconds,
        )

    def verify(self, token: str) -> dict[str, Any]:
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
            audience=self.audience,
            issuer=self.issuer,
            leeway=self.clock_skew_seconds,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
        if not isinstance(claims.get("aud"), (str, list)):
            raise jwt.InvalidAudienceError("aud claim has invalid type")
        return claims
