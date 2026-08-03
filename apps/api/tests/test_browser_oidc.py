from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from korpus.config import Settings
from korpus.main import create_app
from korpus.security.browser_oidc import (
    BrowserOIDCClient,
    BrowserOIDCTokens,
    BrowserSessionCodec,
    BrowserSessionError,
)

from .security_fixtures import write_entitlement_profile


class FakeBrowserClient:
    def new_flow(self):
        return {
            "state": "state-0123456789abcdefghijklmnop",
            "nonce": "nonce-0123456789abcdefghijklmnop",
            "code_verifier": "verifier-" + "x" * 64,
            "code_challenge": "challenge",
            "csrf": "unused",
        }

    def authorization_url(self, flow):
        return "https://id.example/authorize?" + __import__("urllib.parse").parse.urlencode(
            {"state": flow["state"], "code_challenge": flow["code_challenge"]}
        )

    def exchange(self, code, code_verifier):
        assert code == "authorization-code"
        assert code_verifier.startswith("verifier-")
        return BrowserOIDCTokens("access-token", "id-token", 900)

    def close(self):
        return None


class FakeVerifier:
    def verify(self, token, *, audience=None, expected_nonce=None, require_auth_time=True):
        now = int(datetime.now(UTC).timestamp())
        if token == "id-token":
            assert audience == "korpus-browser"
            assert expected_nonce == "nonce-0123456789abcdefghijklmnop"
            return {
                "sub": "browser-user",
                "iss": "https://id.example",
                "aud": "korpus-browser",
                "iat": now,
                "nbf": now,
                "exp": now + 900,
                "jti": "id-jti",
                "auth_time": now,
                "nonce": expected_nonce,
            }
        assert token == "access-token"
        return {
            "sub": "browser-user",
            "iss": "https://id.example",
            "aud": "korpus-api",
            "iat": now,
            "nbf": now,
            "exp": now + 900,
            "jti": "access-jti",
            "auth_time": now,
            "groups": [],
        }

    def close(self):
        return None


def _settings(tmp_path: Path) -> Settings:
    entitlements, digest = write_entitlement_profile(tmp_path)
    return Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'browser.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="audit-key-for-browser-test-only-0000000000",
        auth_mode="oidc",
        oidc_jwks_url="https://id.example/jwks",
        jwt_issuer="https://id.example",
        jwt_audience="korpus-api",
        entitlement_profile_path=entitlements,
        entitlement_profile_sha256=digest,
        browser_auth_enabled=True,
        browser_session_key="browser-session-key-for-tests-000000000000000000",
        browser_cookie_secure=False,
        oidc_authorization_endpoint="https://id.example/authorize",
        oidc_token_endpoint="https://id.example/token",
        oidc_client_id="korpus-browser",
        oidc_redirect_uri="http://testserver/v1/auth/callback",
    )


def test_browser_session_codec_rejects_tampering_and_expiry():
    """Every position, not just the last one.

    This test used to change the final character of the token. base64 pads: when the
    payload length is not a multiple of three, the last character carries bits that no
    input byte uses, so several different characters decode to identical bytes and the
    signature still verifies. The token is not fixed across runs, so whether the last
    character happened to be significant varied — the test failed roughly one run in
    five, and read as flake rather than as a test asserting something it could not
    guarantee.

    Sweeping every position is both deterministic and a stronger claim: any single
    character change that alters the token at all must be rejected.
    """
    clock = [1000.0]
    codec = BrowserSessionCodec("x" * 40, clock=lambda: clock[0])
    token = codec.seal("session", {"access_token": "a", "csrf": "c"}, ttl_seconds=30)
    assert codec.open(token, expected_kind="session")["access_token"] == "a"

    accepted: list[int] = []
    for index in range(len(token)):
        original = token[index]
        if original in "._-":  # structural separators, not payload
            continue
        replacement = "A" if original != "A" else "B"
        tampered = token[:index] + replacement + token[index + 1 :]
        try:
            codec.open(tampered, expected_kind="session")
        except BrowserSessionError:
            continue
        accepted.append(index)
    assert not accepted, (
        f"the codec accepted a token with a changed character at {accepted}; "
        "a single-character edit anywhere in a signed token must not verify"
    )

    clock[0] = 1031.0
    with pytest.raises(BrowserSessionError, match="expired"):
        codec.open(token, expected_kind="session")


def test_oidc_authorization_url_uses_state_nonce_and_s256_pkce():
    client = BrowserOIDCClient(
        authorization_endpoint="https://id.example/authorize",
        token_endpoint="https://id.example/token",
        client_id="browser",
        redirect_uri="https://app.example/callback",
        scopes=["profile"],
    )
    flow = client.new_flow()
    query = parse_qs(urlparse(client.authorization_url(flow)).query)
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [flow["state"]]
    assert query["nonce"] == [flow["nonce"]]
    assert "openid" in query["scope"][0].split()
    client.close()


def test_browser_oidc_callback_keeps_tokens_http_only_and_enforces_csrf(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    with TestClient(app, follow_redirects=False) as client:
        app.state.browser_oidc_client = FakeBrowserClient()
        app.state.oidc_verifier = FakeVerifier()

        login = client.get("/v1/auth/login?return_to=/")
        assert login.status_code == 302
        assert login.headers["location"].startswith("https://id.example/authorize?")
        assert "HttpOnly" in login.headers["set-cookie"]

        callback = client.get(
            "/v1/auth/callback",
            params={
                "code": "authorization-code",
                "state": "state-0123456789abcdefghijklmnop",
            },
        )
        assert callback.status_code == 303, callback.text
        combined_cookies = callback.headers.get_list("set-cookie")
        assert any(
            "__Host-korpus_session=" in value and "HttpOnly" in value
            for value in combined_cookies
        )
        assert all("access-token" not in value for value in combined_cookies)

        identity = client.get("/v1/auth/me")
        assert identity.status_code == 200, identity.text
        assert identity.json()["subject"] == "browser-user"
        assert identity.json()["roles"] == ["user"]

        blocked = client.post("/v1/auth/logout")
        assert blocked.status_code == 403
        csrf = client.cookies.get("__Host-korpus_csrf")
        logout = client.post("/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 204
