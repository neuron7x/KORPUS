"""Transport-shape validation for model egress before locality/classification policy."""

from __future__ import annotations

from korpus.security.external_destination import parse_external_https_url
from korpus.security.url_policy import parse_http_url


def validate_external_model_endpoint(target: str) -> None:
    parse_external_https_url(target, name="external model endpoint", allow_query=False)


def local_model_endpoint_host(target: str) -> str:
    try:
        parts = parse_http_url(target, name="local model endpoint", allow_query=False)
    except ValueError as exc:
        detail = str(exc)
        if "include a host" in detail:
            detail = "endpoint carries no host"
        raise ValueError(detail) from exc
    assert parts.hostname is not None
    return parts.hostname
