"""Strict contracts for metadata identity timing and token payloads."""

from __future__ import annotations

from collections.abc import Mapping

from korpus.application.numeric_contracts import finite_number, require_count, strict_int


def validate_identity_config(
    timeout_seconds: object, refresh_skew_seconds: object
) -> tuple[float, int]:
    if not finite_number(timeout_seconds) or float(timeout_seconds) <= 0.0:
        raise ValueError("metadata timeout_seconds must be finite and positive")
    if not strict_int(refresh_skew_seconds) or refresh_skew_seconds < 0:
        raise ValueError("refresh_skew_seconds must be a non-negative integer")
    return float(timeout_seconds), refresh_skew_seconds


def parse_access_token_payload(payload: object) -> tuple[str, int, str]:
    if not isinstance(payload, Mapping):
        raise ValueError("metadata access-token payload must be an object")
    token = payload.get("access_token")
    token_type = payload.get("token_type", "Bearer")
    if not isinstance(token, str) or not token or not isinstance(token_type, str):
        raise ValueError("metadata access-token fields have invalid types")
    expires_in = require_count(payload.get("expires_in"), positive=True, label="expires_in")
    if token_type.lower() != "bearer":
        raise ValueError("metadata token_type must be Bearer")
    return token, expires_in, token_type
