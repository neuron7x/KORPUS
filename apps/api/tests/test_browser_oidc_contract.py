from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from korpus.security.browser_oidc import BrowserOIDCClient, BrowserSessionCodec, BrowserSessionError


def codec() -> BrowserSessionCodec:
    return BrowserSessionCodec("browser-contract-secret-000000000000", clock=lambda: 1_000)


def authenticated_envelope(value: BrowserSessionCodec, body: Any, kind: str = "session") -> str:
    nonce = b"n" * 12
    plaintext = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ciphertext = AESGCM(value._key).encrypt(nonce, plaintext, kind.encode())
    return value._encode(nonce + ciphertext)


@pytest.mark.parametrize("secret", ["", "x" * 31])
def test_session_secret_and_seal_contract_fail_closed(secret):
    with pytest.raises(ValueError, match="at least 32"):
        BrowserSessionCodec(secret)
    with pytest.raises(ValueError, match="invalid browser session envelope"):
        codec().seal("", {}, ttl_seconds=1)
    with pytest.raises(ValueError, match="invalid browser session envelope"):
        codec().seal("session", {}, ttl_seconds=0)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"v": 2, "kind": "session", "iat": 1_000, "exp": 1_001, "payload": {}}, "type"),
        ({"v": 1, "kind": "other", "iat": 1_000, "exp": 1_001, "payload": {}}, "authentication"),
        ({"v": 1, "kind": "session", "iat": True, "exp": 1_001, "payload": {}}, "timestamps"),
        ({"v": 1, "kind": "session", "iat": 1_000, "exp": False, "payload": {}}, "timestamps"),
        ({"v": 1, "kind": "session", "iat": 1_031, "exp": 1_040, "payload": {}}, "expired"),
        ({"v": 1, "kind": "session", "iat": 1_000, "exp": 1_000, "payload": {}}, "expired"),
        ({"v": 1, "kind": "session", "iat": 1_020, "exp": 1_010, "payload": {}}, "expired"),
        ({"v": 1, "kind": "session", "iat": 1_000, "exp": 1_001, "payload": []}, "payload"),
    ],
)
def test_authenticated_malformed_envelopes_are_rejected(body, message):
    value = codec()
    token = authenticated_envelope(value, body, kind=str(body.get("kind", "session")))
    with pytest.raises(BrowserSessionError, match=message):
        value.open(token, expected_kind="session")


def test_encoding_truncation_and_authenticated_non_json_are_rejected():
    value = codec()
    with pytest.raises(BrowserSessionError, match="encoding"):
        value.open("%", expected_kind="session")
    with pytest.raises(BrowserSessionError, match="encoding"):
        value.open("a", expected_kind="session")
    with pytest.raises(BrowserSessionError, match="truncated"):
        value.open(value._encode(b"short"), expected_kind="session")
    nonce = b"n" * 12
    ciphertext = AESGCM(value._key).encrypt(nonce, b"not-json", b"session")
    with pytest.raises(BrowserSessionError, match="authentication"):
        value.open(value._encode(nonce + ciphertext), expected_kind="session")


def response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def oidc_client(handler, *, secret: str | None = None) -> BrowserOIDCClient:
    transport = httpx.MockTransport(handler)
    return BrowserOIDCClient(
        authorization_endpoint="https://id.example/authorize",
        token_endpoint="https://id.example/token",
        client_id="browser-client",
        redirect_uri="https://app.example/callback",
        scopes=["openid", "profile", "profile"],
        client_secret=secret,
        client=httpx.Client(transport=transport),
    )


def test_oidc_configuration_flow_url_and_exchange_are_canonical():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return response(
            {"access_token": "access", "id_token": "identity", "expires_in": 600,
             "token_type": "Bearer"}
        )

    client = oidc_client(handler, secret="confidential-secret")
    flow = client.new_flow()
    assert len(flow) == 5 and flow["state"] != flow["nonce"]
    assert client.authorization_url(flow).startswith("https://id.example/authorize?")
    assert client.scopes == ("openid", "profile")
    assert client.exchange("code", flow["code_verifier"]).expires_in == 600
    assert "client_secret=confidential-secret" in captured["body"]
    client.close()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "invalid"),
        ({"access_token": "", "id_token": "id", "token_type": "Bearer"}, "incomplete"),
        ({"access_token": "a", "id_token": "", "token_type": "Bearer"}, "incomplete"),
        ({"access_token": "a", "id_token": "i", "token_type": "MAC"}, "type"),
        ({"access_token": "a", "id_token": "i", "token_type": "Bearer", "expires_in": True}, "lifetime"),
        ({"access_token": "a", "id_token": "i", "token_type": "Bearer", "expires_in": 59}, "lifetime"),
        ({"access_token": "a", "id_token": "i", "token_type": "Bearer", "expires_in": 86401}, "lifetime"),
    ],
)
def test_token_response_shape_and_lifetime_fail_closed(payload, message):
    client = oidc_client(lambda request: response(payload))
    with pytest.raises(BrowserSessionError, match=message):
        client.exchange("code", "verifier")
    client.close()


def test_exchange_normalizes_incomplete_http_json_and_transport_failures():
    client = oidc_client(lambda request: response({}, status=503))
    with pytest.raises(BrowserSessionError, match="exchange failed"):
        client.exchange("code", "verifier")
    client.close()

    client = oidc_client(lambda request: httpx.Response(200, content=b"not-json"))
    with pytest.raises(BrowserSessionError, match="exchange failed"):
        client.exchange("code", "verifier")
    client.close()

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = oidc_client(unavailable)
    with pytest.raises(BrowserSessionError, match="exchange failed"):
        client.exchange("code", "verifier")
    with pytest.raises(BrowserSessionError, match="incomplete"):
        client.exchange("", "verifier")
    with pytest.raises(BrowserSessionError, match="incomplete"):
        client.exchange("code", "")
    client.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"authorization_endpoint": "http://id.example/authorize"},
        {"token_endpoint": "http://id.example/token"},
        {"client_id": ""},
        {"redirect_uri": ""},
    ],
)
def test_oidc_client_configuration_rejects_insecure_or_incomplete_values(kwargs):
    values = {
        "authorization_endpoint": "https://id.example/authorize",
        "token_endpoint": "https://id.example/token",
        "client_id": "client",
        "redirect_uri": "https://app.example/callback",
        "scopes": [],
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        BrowserOIDCClient(**values)
