from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from korpus.config import Settings, get_settings
from korpus.domain.models import AccessTier, Identity

bearer = HTTPBearer(auto_error=False)


def issue_token(identity: Identity, settings: Settings, lifetime_minutes: int = 60) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": identity.subject,
        "roles": sorted(identity.roles),
        "clearance": identity.clearance.label(),
        "corpora": sorted(identity.corpora),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(minutes=lifetime_minutes),
    }
    return jwt.encode(payload, settings.resolved_jwt_secret, algorithm="HS256")


def _identity_from_claims(claims: dict[str, Any]) -> Identity:
    try:
        return Identity(
            subject=str(claims["sub"]),
            roles=frozenset(str(role) for role in claims.get("roles", [])),
            clearance=AccessTier.parse(claims.get("clearance", "public")),
            corpora=frozenset(str(corpus) for corpus in claims.get("corpora", ["public"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid identity claims") from exc


def get_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Identity:
    override = getattr(request.app.state, "identity_override", None)
    if override is not None:
        return override
    if settings.auth_mode == "dev":
        return Identity(
            subject=settings.dev_subject,
            roles=frozenset(role.strip() for role in settings.dev_roles.split(",") if role.strip()),
            clearance=AccessTier.parse(settings.dev_clearance),
            corpora=frozenset(corpus.strip() for corpus in settings.dev_corpora.split(",") if corpus.strip()),
        )
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bearer token required")
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.resolved_jwt_secret,
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token") from exc
    return _identity_from_claims(claims)
