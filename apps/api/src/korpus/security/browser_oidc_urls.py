"""OIDC browser URL construction with provider metadata unable to shadow flow state."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from korpus.security.external_destination import parse_external_https_url


def canonical_https_endpoint(value: str, *, name: str) -> str:
    parts = parse_external_https_url(value, name=name)
    return urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))


def authorization_url(
    endpoint: str,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: tuple[str, ...],
    flow: dict[str, str],
) -> str:
    parts = urlsplit(endpoint)
    request_query = [
        ("response_type", "code"),
        ("client_id", client_id),
        ("redirect_uri", redirect_uri),
        ("scope", " ".join(scopes)),
        ("state", flow["state"]),
        ("nonce", flow["nonce"]),
        ("code_challenge", flow["code_challenge"]),
        ("code_challenge_method", "S256"),
        ("prompt", "select_account"),
    ]
    reserved = {name for name, _ in request_query}
    provider_query = [
        (name, value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
        if name not in reserved
    ]
    query = urlencode([*provider_query, *request_query])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
