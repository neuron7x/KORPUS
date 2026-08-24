from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from korpus.config import Settings, get_settings
from korpus.domain.models import AccessTier, Identity
from korpus.security.browser_oidc import BrowserSessionError
from korpus.security.entitlements import EntitlementProfile

bearer = HTTPBearer(auto_error=False)
_LOOPBACKS = {"127.0.0.1", "::1", "localhost", "testclient", "testserver"}


def issue_token(identity: Identity, settings: Settings, lifetime_minutes: int = 60) -> str:
    if settings.auth_mode not in {"dev", "jwt"}:
        raise ValueError("local token issuance is unavailable for this authentication mode")
    if lifetime_minutes <= 0 or lifetime_minutes > settings.jwt_max_lifetime_minutes:
        raise ValueError("token lifetime exceeds configured maximum")
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": identity.subject,
        "roles": sorted(identity.roles),
        "clearance": identity.clearance.label(),
        "corpora": sorted(identity.corpora),
        "compartments": sorted(identity.compartments),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": str(uuid4()),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=lifetime_minutes),
    }
    return jwt.encode(payload, settings.resolved_jwt_secret, algorithm="HS256")


def _identity_from_local_claims(claims: dict[str, Any]) -> Identity:
    try:
        return Identity(
            subject=str(claims["sub"]),
            roles=frozenset(str(role) for role in claims.get("roles", [])),
            clearance=AccessTier.parse(claims.get("clearance", "public")),
            corpora=frozenset(str(corpus) for corpus in claims.get("corpora", ["public"])),
            compartments=frozenset(
                str(compartment) for compartment in claims.get("compartments", [])
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid identity claims"
        ) from exc


def _validate_lifetime(claims: dict[str, Any], settings: Settings) -> None:
    try:
        issued = datetime.fromtimestamp(float(claims["iat"]), tz=UTC)
        expires = datetime.fromtimestamp(float(claims["exp"]), tz=UTC)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token timestamps"
        ) from exc
    if expires <= issued or expires - issued > timedelta(minutes=settings.jwt_max_lifetime_minutes):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token lifetime exceeds policy"
        )


@lru_cache(maxsize=16)
def _load_entitlement_profile(
    path: str, digest: str | None, content_key: str
) -> EntitlementProfile:
    """Parse the profile. `content_key` is part of the cache key, not of the load."""

    del content_key
    return EntitlementProfile.load(Path(path), digest)


def load_entitlement_profile(path: str, digest: str | None) -> EntitlementProfile:
    """Load the entitlement profile, honouring revocations written since start-up.

    The cache used to be keyed on the path alone, which froze the profile for the life
    of the process: a subject added to `deny_subjects` on disk kept every right it had
    (probe: `REVOCATION IGNORED ['reviewer']`), and nothing — not `/ready`, not a new
    request — re-read the file. Restarting the API is not a revocation mechanism.

    The key is the file's content, so a revocation takes effect on the next request and
    an unchanged file is still parsed once. Reading the bytes on each call is
    deliberate and is the whole cost of the check; parsing and validation, which are
    the expensive parts, stay cached. A pinned digest that no longer matches raises
    rather than falling back to the profile already in memory: refusing to serve a
    changed profile is the fail-closed direction, and continuing to serve the old one
    is precisely the behaviour being removed.
    """

    return _load_entitlement_profile(
        path, digest, hashlib.sha256(Path(path).read_bytes()).hexdigest()
    )


def _oidc_identity(claims: dict[str, Any], settings: Settings) -> Identity:
    if settings.entitlement_profile_path is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="server-side entitlement profile is unavailable",
        )
    try:
        profile = load_entitlement_profile(
            str(settings.entitlement_profile_path.resolve()), settings.entitlement_profile_sha256
        )
        return profile.resolve(claims)
    except (OSError, ValueError, PermissionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="identity has no active entitlement"
        ) from exc


def _dev_identity(settings: Settings, request: Request) -> Identity:
    client_host = request.client.host if request.client is not None else ""
    if client_host not in _LOOPBACKS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="dev auth is loopback-only"
        )
    return Identity(
        subject=settings.dev_subject,
        roles=frozenset(role.strip() for role in settings.dev_roles.split(",") if role.strip()),
        clearance=AccessTier.parse(settings.dev_clearance),
        corpora=frozenset(
            corpus.strip() for corpus in settings.dev_corpora.split(",") if corpus.strip()
        ),
        compartments=frozenset(
            value.strip() for value in settings.dev_compartments.split(",") if value.strip()
        ),
    )


def get_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
) -> Identity:
    if settings.auth_mode == "disabled":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="authentication disabled"
        )
    if settings.auth_mode == "dev":
        return _dev_identity(settings, request)
    token = credentials.credentials if credentials is not None else None
    if token is None and settings.auth_mode == "oidc" and settings.browser_auth_enabled:
        session_cookie = request.cookies.get(settings.browser_session_cookie)
        codec = getattr(request.app.state, "browser_session_codec", None)
        if session_cookie and codec is not None:
            try:
                session = codec.open(session_cookie, expected_kind="session")
                token_value = session.get("access_token")
                if not isinstance(token_value, str) or not token_value:
                    raise BrowserSessionError("browser session has no access token")
                token = token_value
                request.state.cookie_authenticated = True
                request.state.browser_csrf = session.get("csrf")
            except BrowserSessionError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid browser session"
                ) from exc
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    try:
        if settings.auth_mode == "jwt":
            claims = jwt.decode(
                token,
                settings.resolved_jwt_secret,
                algorithms=["HS256"],
                audience=settings.jwt_audience,
                issuer=settings.jwt_issuer,
                options={"require": ["sub", "exp", "iat", "nbf", "jti", "iss", "aud"]},
            )
        else:
            verifier = getattr(request.app.state, "oidc_verifier", None)
            if verifier is None:
                raise jwt.InvalidTokenError("OIDC verifier is unavailable")
            claims = verifier.verify(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token"
        ) from exc
    _validate_lifetime(claims, settings)
    if settings.auth_mode == "oidc":
        return _oidc_identity(claims, settings)
    return _identity_from_local_claims(claims)
