"""Fail-closed parsing for HTTPS destinations that must be outside the deployment."""

from __future__ import annotations

import ipaddress
from urllib.parse import SplitResult

from korpus.security.url_policy import parse_https_url


def parse_external_https_url(
    value: str, *, name: str = "external URL", allow_query: bool = True) -> SplitResult:
    parts = parse_https_url(value, name=name, allow_query=allow_query)
    if not (hostname := parts.hostname):
        raise ValueError(f"{name} must include a host")
    host = hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError(f"{name} must not target localhost")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return parts
    if not address.is_global:
        raise ValueError(f"{name} must use a globally routable address")
    return parts
