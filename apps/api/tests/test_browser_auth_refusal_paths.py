"""Every refusal in the browser OIDC routes, none of which had a test.

`test_browser_oidc.py` drives the accepting path end to end. Measured on 2026-08-28,
`routes_auth.py` sat at 56% branch coverage and every uncovered branch was a refusal:
the open-redirect filter, both disabled-feature guards, the missing-dependency guard,
the missing-flow-cookie guard, the state comparison and the subject-binding check.

That distribution is the dangerous one. A refusal with no test is a refusal that can be
deleted, inverted or short-circuited without turning the suite red — and each of these
five is the only thing standing between the callback and a known attack: open redirect,
CSRF via state fixation, and access-token substitution across subjects.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from korpus.api.routes_auth import _safe_return_path
from korpus.main import create_app

from .test_browser_oidc import FakeBrowserClient, FakeVerifier, _settings

STATE = "state-0123456789abcdefghijklmnop"


@pytest.mark.parametrize(
    "hostile",
    [
        "//evil.example/takeover",
        "///evil.example",
        "https://evil.example",
        "\\\\evil.example",
        "/ok\\evil",
        "evil.example",
        "",
    ],
)
def test_a_return_path_that_could_leave_the_origin_collapses_to_root(hostile: str) -> None:
    """`//host` is a protocol-relative URL: the browser reads it as another origin.

    The check is not "starts with a slash" — that admits `//evil.example`, which is the
    canonical open-redirect payload. A backslash is included because some clients
    normalise it to a forward slash before following the location header.
    """
    assert _safe_return_path(hostile) == "/"


def test_a_same_origin_return_path_survives_and_is_bounded() -> None:
    assert _safe_return_path("/workspace/answers") == "/workspace/answers"
    assert len(_safe_return_path("/" + "a" * 4096)) == 1024


def test_login_and_callback_are_not_found_when_browser_auth_is_off(tmp_path: Path) -> None:
    """404, not 403: an endpoint that is off should not advertise that it exists."""
    settings = _settings(tmp_path).model_copy(update={"browser_auth_enabled": False})
    app = create_app(settings)
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/v1/auth/login").status_code == 404
        assert client.get(
            "/v1/auth/callback", params={"code": "c", "state": STATE}
        ).status_code == 404


def test_login_refuses_when_the_oidc_client_was_never_wired(tmp_path: Path) -> None:
    """Enabled but unwired is a deployment fault, so 503 — never a redirect to nowhere."""
    app = create_app(_settings(tmp_path))
    with TestClient(app, follow_redirects=False) as client:
        app.state.browser_oidc_client = None
        app.state.browser_session_codec = None
        assert client.get("/v1/auth/login").status_code == 503


def test_a_callback_without_the_flow_cookie_is_refused(tmp_path: Path) -> None:
    """The cookie carries the state and the PKCE verifier; without it nothing is bound."""
    app = create_app(_settings(tmp_path))
    with TestClient(app, follow_redirects=False) as client:
        app.state.browser_oidc_client = FakeBrowserClient()
        app.state.oidc_verifier = FakeVerifier()
        response = client.get("/v1/auth/callback", params={"code": "c", "state": STATE})
    assert response.status_code == 401


def test_a_state_that_does_not_match_the_sealed_flow_is_refused(tmp_path: Path) -> None:
    """State fixation: the attacker supplies the code, the victim's cookie supplies the flow."""
    app = create_app(_settings(tmp_path))
    with TestClient(app, follow_redirects=False) as client:
        app.state.browser_oidc_client = FakeBrowserClient()
        app.state.oidc_verifier = FakeVerifier()
        assert client.get("/v1/auth/login").status_code == 302
        response = client.get(
            "/v1/auth/callback",
            params={"code": "authorization-code", "state": "state-ZZZZZZZZZZZZZZZZZZZZ"},
        )
    assert response.status_code == 401
    assert "__Host-korpus_session" not in response.headers.get("set-cookie", "")


def test_an_access_token_for_a_different_subject_is_refused(tmp_path: Path) -> None:
    """Token substitution: both tokens verify, and they describe two different people.

    Verifying each token in isolation is not enough. The session is sealed around the
    access token, so if the id token names the visitor and the access token names
    somebody else, the browser would carry a session acting as that other subject.
    """

    class MismatchedVerifier(FakeVerifier):
        def verify(self, token, **kwargs):
            claims = dict(super().verify(token, **kwargs))
            if token != "id-token":
                claims["sub"] = "somebody-else"
            return claims

    app = create_app(_settings(tmp_path))
    with TestClient(app, follow_redirects=False) as client:
        app.state.browser_oidc_client = FakeBrowserClient()
        app.state.oidc_verifier = MismatchedVerifier()
        assert client.get("/v1/auth/login").status_code == 302
        response = client.get(
            "/v1/auth/callback", params={"code": "authorization-code", "state": STATE}
        )
    assert response.status_code == 401
    assert "__Host-korpus_session" not in response.headers.get("set-cookie", "")
