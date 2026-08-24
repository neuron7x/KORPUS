"""Numeric contracts for OIDC freshness and cache timing."""

from __future__ import annotations

from datetime import UTC, datetime

from korpus.application.numeric_contracts import finite_number, require_count


def _positive_timeout(value: object) -> float:
    if not finite_number(value) or float(value) <= 0.0:
        raise ValueError("http_timeout_seconds must be finite and positive")
    return float(value)


def validate_oidc_timing(
    jwks_cache_seconds: object,
    http_timeout_seconds: object,
    clock_skew_seconds: object,
    max_auth_age_seconds: object,
) -> tuple[int, float, int, int]:
    cache = require_count(jwks_cache_seconds, positive=True, label="jwks_cache_seconds")
    timeout = _positive_timeout(http_timeout_seconds)
    skew = require_count(clock_skew_seconds, label="clock_skew_seconds")
    max_age = require_count(max_auth_age_seconds, positive=True, label="max_auth_age_seconds")
    if max_age < 60:
        raise ValueError("max_auth_age_seconds is too small")
    return cache, timeout, skew, max_age


def numeric_date(value: object, *, claim: str) -> datetime:
    if not finite_number(value):
        raise ValueError(f"{claim} claim must be a finite NumericDate")
    return datetime.fromtimestamp(float(value), tz=UTC)
