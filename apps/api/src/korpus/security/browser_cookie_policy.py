"""Single browser-cookie policy boundary for OIDC/BFF state transitions."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Request, Response


def validate_browser_cookie_policy(settings: Any, *, controlled: bool) -> None:
    names = (
        settings.browser_session_cookie,
        settings.browser_csrf_cookie,
        settings.browser_flow_cookie,
    )
    if len(set(names)) != len(names):
        raise ValueError("browser session, CSRF, and flow cookie names must be distinct")
    if not controlled:
        return
    if not settings.browser_cookie_secure:
        raise ValueError("controlled browser cookies must be Secure")
    if not settings.browser_session_cookie.startswith("__Host-"):
        raise ValueError("controlled browser session cookie must use the __Host- prefix")
    if not settings.browser_csrf_cookie.startswith("__Host-"):
        raise ValueError("controlled browser CSRF cookie must use the __Host- prefix")
    if not settings.browser_flow_cookie.startswith("__Secure-"):
        raise ValueError("controlled browser flow cookie must use the __Secure- prefix")
    if settings.resolved_browser_session_key.startswith("replace-"):
        raise ValueError("controlled browser session key must not be a placeholder")


def browser_csrf_pair_valid(request: Request, settings: Any) -> bool:
    supplied = request.headers.get("X-CSRF-Token", "")
    cookie = request.cookies.get(settings.browser_csrf_cookie, "")
    return bool(supplied and cookie and secrets.compare_digest(supplied, cookie))


def set_flow_cookie(response: Response, settings: Any, value: str) -> None:
    response.set_cookie(
        settings.browser_flow_cookie,
        value,
        max_age=settings.browser_flow_ttl_seconds,
        httponly=True,
        secure=settings.browser_cookie_secure,
        samesite="lax",
        path="/v1/auth",
    )


def clear_flow_cookie(response: Response, settings: Any) -> None:
    response.delete_cookie(
        settings.browser_flow_cookie,
        path="/v1/auth",
        secure=settings.browser_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def set_session_cookies(
    response: Response, settings: Any, session_cookie: str, csrf: str, ttl: int
) -> None:
    response.set_cookie(
        settings.browser_session_cookie,
        session_cookie,
        max_age=ttl,
        httponly=True,
        secure=settings.browser_cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        settings.browser_csrf_cookie,
        csrf,
        max_age=ttl,
        httponly=False,
        secure=settings.browser_cookie_secure,
        samesite="strict",
        path="/",
    )


def clear_browser_cookies(response: Response, settings: Any) -> None:
    response.delete_cookie(
        settings.browser_session_cookie,
        path="/",
        secure=settings.browser_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        settings.browser_csrf_cookie,
        path="/",
        secure=settings.browser_cookie_secure,
        httponly=False,
        samesite="strict",
    )
    clear_flow_cookie(response, settings)
