from __future__ import annotations

import hmac
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from starlette.responses import RedirectResponse

from korpus.config import Settings, get_settings
from korpus.domain.models import Identity
from korpus.security.auth import get_identity
from korpus.security.browser_oidc import BrowserSessionError


router = APIRouter()
IdentityDependency = Annotated[Identity, Depends(get_identity)]


def _safe_return_path(value: str) -> str:
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value[:1024]


@router.get("/v1/auth/login", include_in_schema=False)
def browser_login(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    return_to: Annotated[str, Query(max_length=1024)] = "/",
) -> Response:
    if not settings.browser_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="browser authentication disabled"
        )
    client = getattr(request.app.state, "browser_oidc_client", None)
    codec = getattr(request.app.state, "browser_session_codec", None)
    if client is None or codec is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="browser authentication unavailable",
        )
    flow = client.new_flow()
    flow_cookie = codec.seal(
        "flow",
        {
            "state": flow["state"],
            "nonce": flow["nonce"],
            "code_verifier": flow["code_verifier"],
            "return_to": _safe_return_path(return_to),
        },
        ttl_seconds=settings.browser_flow_ttl_seconds,
    )
    response = RedirectResponse(client.authorization_url(flow), status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        settings.browser_flow_cookie,
        flow_cookie,
        max_age=settings.browser_flow_ttl_seconds,
        httponly=True,
        secure=settings.browser_cookie_secure,
        samesite="lax",
        path="/v1/auth",
    )
    return response


@router.get("/v1/auth/callback", include_in_schema=False)
def browser_callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str, Query(min_length=1, max_length=4096)],
    state_value: Annotated[str, Query(alias="state", min_length=16, max_length=512)],
) -> Response:
    if not settings.browser_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="browser authentication disabled"
        )
    flow_cookie = request.cookies.get(settings.browser_flow_cookie)
    client = getattr(request.app.state, "browser_oidc_client", None)
    codec = getattr(request.app.state, "browser_session_codec", None)
    verifier = getattr(request.app.state, "oidc_verifier", None)
    if not flow_cookie or client is None or codec is None or verifier is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="OIDC flow state unavailable"
        )
    try:
        flow = codec.open(flow_cookie, expected_kind="flow")
        expected_state = flow.get("state")
        if not isinstance(expected_state, str) or not hmac.compare_digest(
            expected_state, state_value
        ):
            raise BrowserSessionError("OIDC state mismatch")
        tokens = client.exchange(code, str(flow.get("code_verifier", "")))
        id_claims = verifier.verify(
            tokens.id_token,
            audience=settings.oidc_client_id,
            expected_nonce=str(flow.get("nonce", "")),
        )
        access_claims = verifier.verify(tokens.access_token)
        if str(id_claims.get("sub")) != str(access_claims.get("sub")):
            raise BrowserSessionError("OIDC token subjects differ")
        csrf = __import__("secrets").token_urlsafe(32)
        ttl = min(settings.browser_session_ttl_seconds, tokens.expires_in)
        session_cookie = codec.seal(
            "session",
            {"access_token": tokens.access_token, "csrf": csrf},
            ttl_seconds=ttl,
        )
    except (BrowserSessionError, ValueError, jwt.PyJWTError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="OIDC callback validation failed"
        ) from exc
    response = RedirectResponse(
        _safe_return_path(str(flow.get("return_to", "/"))),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.delete_cookie(settings.browser_flow_cookie, path="/v1/auth")
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
    return response


@router.post("/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
def browser_logout(settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.browser_session_cookie, path="/")
    response.delete_cookie(settings.browser_csrf_cookie, path="/")
    response.delete_cookie(settings.browser_flow_cookie, path="/v1/auth")
    return response


@router.get("/v1/auth/me", response_model=Identity)
def me(identity: IdentityDependency) -> Identity:
    return identity
