"""Small, independently testable OIDC claim predicates used after signature verification."""
from __future__ import annotations

import secrets
from typing import Any

import jwt

ALLOWED_ASYMMETRIC_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
)
ACCEPTED_TOKEN_TYPES = frozenset({"jwt", "at+jwt"})


def validate_algorithms(algorithms: list[str]) -> tuple[str, ...]:
    if (
        not algorithms
        or len(set(algorithms)) != len(algorithms)
        or any(algorithm not in ALLOWED_ASYMMETRIC_ALGORITHMS for algorithm in algorithms)
    ):
        raise ValueError("OIDC algorithms must be asymmetric, supported, unique, and explicitly pinned")
    return tuple(algorithms)


def validate_header(token: str, algorithms: tuple[str, ...]) -> None:
    header = jwt.get_unverified_header(token)
    algorithm = str(header.get("alg", ""))
    if algorithm not in algorithms:
        raise jwt.InvalidAlgorithmError("token algorithm is not allowed")
    if not str(header.get("kid", "")):
        raise jwt.InvalidTokenError("token kid is required for rotation-safe verification")
    token_type = header.get("typ")
    if token_type is not None and str(token_type).casefold() not in ACCEPTED_TOKEN_TYPES:
        raise jwt.InvalidTokenError("token typ is not an accepted JWT media type")


def validate_audience_and_authorized_party(
    claims: dict[str, Any], authorized_party: str | None
) -> None:
    audience = claims.get("aud")
    if not isinstance(audience, (str, list)):
        raise jwt.InvalidAudienceError("aud claim has invalid type")
    if isinstance(audience, list):
        if not audience or any(not isinstance(item, str) or not item for item in audience):
            raise jwt.InvalidAudienceError("aud claim contains invalid audience values")
        if len(audience) > 1 and (not isinstance(claims.get("azp"), str) or not claims.get("azp")):
            raise jwt.InvalidTokenError("multi-audience OIDC token requires azp")
    token_azp = claims.get("azp")
    if authorized_party is not None and token_azp is not None and token_azp != authorized_party:
        raise jwt.InvalidTokenError("OIDC azp does not match the authorized party")


def validate_nonce(claims: dict[str, Any], expected_nonce: str | None) -> None:
    if expected_nonce is None:
        return
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not secrets.compare_digest(nonce, expected_nonce):
        raise jwt.InvalidTokenError("OIDC nonce mismatch")
