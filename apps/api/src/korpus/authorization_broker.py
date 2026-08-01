from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from korpus.security.database_capability import DatabaseCapabilityIssuer
from korpus.security.entitlements import EntitlementProfile
from korpus.security.oidc import OIDCVerifier

bearer = HTTPBearer(auto_error=False)


class CredentialVerifier(Protocol):
    def verify(self, token: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class BrokerRuntime:
    verifier: CredentialVerifier
    entitlements: EntitlementProfile
    issuer: DatabaseCapabilityIssuer
    lifetime_seconds: int = 30

    def __post_init__(self) -> None:
        if not 5 <= self.lifetime_seconds <= 60:
            raise ValueError("database capability lifetime must be between 5 and 60 seconds")

    def issue(self, credential: str) -> str:
        claims = self.verifier.verify(credential)
        identity = self.entitlements.resolve(claims)
        operations = {"read"}
        if identity.has_role("curator", "admin", "worker"):
            operations.add("write")
        if identity.has_role("admin"):
            operations.add("delete")
        now = datetime.now(UTC)
        capability: str = self.issuer.issue(
            identity,
            jti=secrets.token_urlsafe(24),
            not_before=now - timedelta(seconds=1),
            expires_at=now + timedelta(seconds=self.lifetime_seconds),
            operations=frozenset(operations),
        )
        return capability


def create_broker_app(runtime: BrokerRuntime) -> FastAPI:
    app = FastAPI(title="KORPUS Database Authorization Broker", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/database-capabilities")
    def issue_capability(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> dict[str, str]:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="OIDC bearer credential is required",
            )
        try:
            capability = runtime.issue(credentials.credentials)
        except (jwt.PyJWTError, PermissionError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="credential is not entitled to a database capability",
            ) from exc
        return {"capability": capability}

    return app


def create_app_from_env() -> FastAPI:
    profile_path = Path(os.environ["KORPUS_BROKER_ENTITLEMENT_PROFILE_PATH"])
    profile_digest = os.environ["KORPUS_BROKER_ENTITLEMENT_PROFILE_SHA256"]
    entitlements = EntitlementProfile.load(profile_path, profile_digest)
    issuer = DatabaseCapabilityIssuer(
        os.environ["KORPUS_DATABASE_CAPABILITY_KEY_ID"],
        Path(os.environ["KORPUS_DATABASE_CAPABILITY_KEY_FILE"]).read_bytes().strip(),
    )
    verifier = OIDCVerifier(
        jwks_url=os.environ["KORPUS_BROKER_OIDC_JWKS_URL"],
        issuer=os.environ["KORPUS_BROKER_OIDC_ISSUER"],
        audience=os.environ["KORPUS_BROKER_OIDC_AUDIENCE"],
        algorithms=tuple(
            value.strip()
            for value in os.getenv("KORPUS_BROKER_OIDC_ALGORITHMS", "RS256,ES256").split(",")
            if value.strip()
        ),
        jwks_cache_seconds=int(os.getenv("KORPUS_BROKER_JWKS_CACHE_SECONDS", "300")),
        http_timeout_seconds=float(os.getenv("KORPUS_BROKER_HTTP_TIMEOUT_SECONDS", "5")),
        clock_skew_seconds=int(os.getenv("KORPUS_BROKER_CLOCK_SKEW_SECONDS", "30")),
        required_acr=os.getenv("KORPUS_BROKER_REQUIRED_ACR") or None,
        require_mfa=os.getenv("KORPUS_BROKER_REQUIRE_MFA", "true").lower() == "true",
        max_auth_age_seconds=int(os.getenv("KORPUS_BROKER_MAX_AUTH_AGE_SECONDS", "3600")),
    )
    return create_broker_app(
        BrokerRuntime(
            verifier=verifier,
            entitlements=entitlements,
            issuer=issuer,
            lifetime_seconds=int(os.getenv("KORPUS_BROKER_CAPABILITY_TTL_SECONDS", "30")),
        )
    )
