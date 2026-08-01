from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Connection

from korpus.domain.models import Classification, Identity

CAPABILITY_AUDIENCE = "korpus-db"
CAPABILITY_VERSION = 1


class DatabaseCapabilityProvider(Protocol):
    def issue(self, identity: Identity) -> str: ...


class HttpDatabaseCapabilityProvider:
    """Fetch one capability without allowing the API to request broader claims."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 3.0,
        ca_file: Path | None = None,
        workload_credential_file: Path | None = None,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("database capability broker endpoint must use HTTPS")
        self.endpoint = endpoint
        self.workload_credential_file = workload_credential_file
        self.client = httpx.Client(
            timeout=timeout_seconds, verify=str(ca_file) if ca_file is not None else True
        )

    def issue(self, identity: Identity) -> str:
        credential = identity.authorization_credential
        if credential is None and self.workload_credential_file is not None:
            try:
                credential = self.workload_credential_file.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise PermissionError("workload authorization credential is unavailable") from exc
        if not credential:
            raise PermissionError("original authorization credential is unavailable")
        try:
            response = self.client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PermissionError("database capability broker rejected issuance") from exc
        capability = payload.get("capability") if isinstance(payload, dict) else None
        if not isinstance(capability, str) or not 66 <= len(capability) <= 8192:
            raise PermissionError("database capability broker returned an invalid response")
        return capability

    def close(self) -> None:
        self.client.close()


class LocalDatabaseCapabilityProvider:
    """Development-only issuer; never satisfies the independent controlled boundary."""

    def __init__(self, key_id: str, key_file: Path) -> None:
        self.issuer = DatabaseCapabilityIssuer(key_id, key_file.read_bytes().strip())

    def issue(self, identity: Identity) -> str:
        now = datetime.now(UTC)
        operations = {"read"}
        if identity.has_role("curator", "admin", "worker"):
            operations.add("write")
        if identity.has_role("admin"):
            operations.add("delete")
        return self.issuer.issue(
            identity,
            jti=secrets.token_urlsafe(24),
            not_before=now - timedelta(seconds=1),
            expires_at=now + timedelta(seconds=30),
            operations=frozenset(operations),
        )


def activate_database_capability(
    connection: Connection,
    identity: Identity,
    provider: DatabaseCapabilityProvider | None,
) -> None:
    if connection.dialect.name != "postgresql":
        return
    capability = provider.issue(identity) if provider is not None else identity.database_capability
    if capability is None:
        raise PermissionError("PostgreSQL authorization capability is required")
    connection.execute(
        text("SELECT korpus_auth.activate(:capability)"), {"capability": capability}
    )


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class DatabaseCapabilityIssuer:
    """Reference issuer for a separate trust process and deterministic tests.

    Never construct this object inside the API runtime. The symmetric key is shared only
    between an independently protected issuer and the PostgreSQL authorization schema.
    """

    key_id: str
    key: bytes

    def __post_init__(self) -> None:
        if not self.key_id or len(self.key_id) > 128:
            raise ValueError("capability key_id must contain 1..128 characters")
        if len(self.key) < 32:
            raise ValueError("capability signing key must contain at least 32 bytes")

    def issue(
        self,
        identity: Identity,
        *,
        jti: str,
        not_before: datetime,
        expires_at: datetime,
        operations: frozenset[str] = frozenset({"read"}),
    ) -> str:
        if not jti or len(jti) > 200:
            raise ValueError("capability jti must contain 1..200 characters")
        if not_before.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("capability timestamps must be timezone-aware")
        if expires_at <= not_before:
            raise ValueError("capability expiry must follow not-before")
        allowed_operations = frozenset({"read", "write", "delete"})
        if not operations or not operations <= allowed_operations:
            raise ValueError("capability contains unsupported operations")
        payload: dict[str, Any] = {
            "aud": CAPABILITY_AUDIENCE,
            "classifications": [
                value.value
                for value in Classification
                if identity.clearance >= value.minimum_tier
            ],
            "clearance": int(identity.clearance),
            "compartments": sorted(identity.compartments),
            "corpora": sorted(identity.corpora),
            "exp": int(expires_at.astimezone(UTC).timestamp()),
            "jti": jti,
            "key_id": self.key_id,
            "nbf": int(not_before.astimezone(UTC).timestamp()),
            "operations": sorted(operations),
            "roles": sorted(identity.roles),
            "sub": identity.subject,
            "v": CAPABILITY_VERSION,
        }
        encoded = _b64url(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        )
        signature = hmac.new(self.key, encoded.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"
