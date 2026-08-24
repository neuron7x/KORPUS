"""Fail-closed browser CSRF decision isolated from HTTP orchestration."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Request

from korpus.config import Settings
from korpus.security.browser_oidc import BrowserSessionError

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def browser_csrf_denial(
    app: Any, request: Request, settings: Settings, session_cookie: str | None
) -> tuple[int, str] | None:
    if request.method not in _MUTATING or not settings.browser_auth_enabled or not session_cookie:
        return None
    codec = getattr(app.state, "browser_session_codec", None)
    try:
        session = codec.open(session_cookie, expected_kind="session") if codec else {}
        expected = session.get("csrf")
    except BrowserSessionError:
        return 401, "invalid browser session"
    supplied = request.headers.get("X-CSRF-Token", "")
    cookie = request.cookies.get(settings.browser_csrf_cookie, "")
    valid = (
        isinstance(expected, str)
        and bool(supplied)
        and bool(cookie)
        and secrets.compare_digest(supplied, expected)
        and secrets.compare_digest(cookie, expected)
    )
    return None if valid else (403, "CSRF validation failed")
