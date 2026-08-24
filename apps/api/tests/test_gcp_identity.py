from __future__ import annotations

import httpx
import pytest

from korpus.infrastructure.gcp_identity import MetadataIdentityError, MetadataIdentityProvider


def test_metadata_access_token_is_cached_and_uses_required_flavor_header() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Metadata-Flavor"] == "Google"
        return httpx.Response(
            200,
            headers={"Metadata-Flavor": "Google"},
            json={"access_token": "token-1", "expires_in": 3600, "token_type": "Bearer"},
        )

    clock = [100.0]
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = MetadataIdentityProvider(client=client, clock=lambda: clock[0])

    assert provider.access_token() == "token-1"
    assert provider.authorization_header() == "Bearer token-1"
    assert len(calls) == 1


def test_metadata_token_refreshes_before_expiry() -> None:
    counter = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal counter
        counter += 1
        return httpx.Response(
            200,
            headers={"Metadata-Flavor": "Google"},
            json={"access_token": f"token-{counter}", "expires_in": 120, "token_type": "Bearer"},
        )

    clock = [0.0]
    provider = MetadataIdentityProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        refresh_skew_seconds=60,
        clock=lambda: clock[0],
    )
    assert provider.access_token() == "token-1"
    clock[0] = 61.0
    assert provider.access_token() == "token-2"


def test_metadata_identity_fails_closed_on_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"Metadata-Flavor": "Google"})

    provider = MetadataIdentityProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MetadataIdentityError, match="unavailable"):
        provider.access_token()


def test_id_token_refuses_non_https_audience() -> None:
    provider = MetadataIdentityProvider(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(ValueError, match="HTTPS"):
        provider.id_token("http://internal.example")
