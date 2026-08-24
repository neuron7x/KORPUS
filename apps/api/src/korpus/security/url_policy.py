"""Canonical URL parsing for security-sensitive configuration and outbound endpoints."""

from __future__ import annotations

from urllib.parse import SplitResult, urlsplit


def _split_web_url(value: str, *, name: str) -> SplitResult:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} is empty or contains surrounding whitespace")
    if "\\" in value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"{name} contains forbidden URL characters")
    try:
        parts = urlsplit(value)
        _ = parts.port  # force malformed/non-numeric port validation
    except ValueError as exc:
        raise ValueError(f"{name} is not a valid URL") from exc
    return parts


def _validate_authority(parts: SplitResult, *, name: str) -> None:
    if not parts.hostname:
        raise ValueError(f"{name} must include a host")
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"{name} must not contain URL credentials")
    if parts.fragment:
        raise ValueError(f"{name} must not contain a fragment")


def _validate_shape(parts: SplitResult, *, name: str, allow_query: bool, origin_only: bool) -> None:
    if not allow_query and parts.query:
        raise ValueError(f"{name} must not contain a query")
    if origin_only and (parts.path not in {"", "/"} or parts.query):
        raise ValueError(f"{name} must be an origin without path or query")


def parse_https_url(
    value: str,
    *,
    name: str = "URL",
    allow_query: bool = True,
    origin_only: bool = False,
) -> SplitResult:
    """Return one unambiguous HTTPS interpretation or fail closed."""
    parts = _split_web_url(value, name=name)
    if parts.scheme.casefold() != "https":
        raise ValueError(f"{name} must use HTTPS and include a host")
    _validate_authority(parts, name=name)
    _validate_shape(parts, name=name, allow_query=allow_query, origin_only=origin_only)
    return parts


def parse_http_url(
    value: str,
    *,
    name: str = "URL",
    allow_query: bool = True,
    origin_only: bool = False,
) -> SplitResult:
    """Return one unambiguous HTTP(S) interpretation or fail closed."""
    parts = _split_web_url(value, name=name)
    if parts.scheme.casefold() not in {"http", "https"}:
        raise ValueError(f"{name} must use HTTP(S) and include a host")
    _validate_authority(parts, name=name)
    _validate_shape(parts, name=name, allow_query=allow_query, origin_only=origin_only)
    return parts


def is_https_url(value: object, *, allow_query: bool = True, origin_only: bool = False) -> bool:
    try:
        parse_https_url(str(value), allow_query=allow_query, origin_only=origin_only)
    except (TypeError, ValueError):
        return False
    return True


def is_explicit_loopback_http_url(
    value: object, *, allow_query: bool = True, origin_only: bool = False
) -> bool:
    try:
        parts = parse_http_url(str(value), allow_query=allow_query, origin_only=origin_only)
    except (TypeError, ValueError):
        return False
    return parts.scheme.casefold() == "http" and parts.hostname in {
        "127.0.0.1",
        "::1",
        "localhost",
        "testserver",
    }


def is_explicit_loopback_http_origin(value: object) -> bool:
    return is_explicit_loopback_http_url(value, allow_query=False, origin_only=True)


def is_https_origin(value: object) -> bool:
    return is_https_url(value, origin_only=True)


def is_https_or_loopback_url(value: object) -> bool:
    return is_https_url(value) or is_explicit_loopback_http_url(value)


def is_https_or_loopback_origin(value: object) -> bool:
    return is_https_origin(value) or is_explicit_loopback_http_origin(value)


def is_browser_redirect_url(value: object) -> bool:
    return is_https_or_loopback_url(value)
