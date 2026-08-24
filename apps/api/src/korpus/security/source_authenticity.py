from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, Field, model_validator

from korpus.domain.models import AuthorityClass, VersionCreate


class SourceTrustKey(BaseModel):
    key_id: str = Field(min_length=3, max_length=200)
    issuer: str = Field(min_length=2, max_length=300)
    public_key_b64: str = Field(min_length=40, max_length=100)
    authorities: frozenset[AuthorityClass] = Field(default_factory=frozenset)
    valid_from: date | None = None
    valid_until: date | None = None
    revoked: bool = False

    @model_validator(mode="after")
    def validate_dates(self) -> SourceTrustKey:
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("source trust key validity interval is invalid")
        raw = base64.b64decode(self.public_key_b64, validate=True)
        if len(raw) != 32:
            raise ValueError("Ed25519 public key must be 32 bytes")
        return self


class SourceTrustProfile(BaseModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    profile_id: str = Field(min_length=3, max_length=120)
    keys: dict[str, SourceTrustKey]

    @model_validator(mode="after")
    def validate_keys(self) -> SourceTrustProfile:
        if not self.keys:
            raise ValueError("source trust profile requires at least one key")
        for identifier, key in self.keys.items():
            if identifier != key.key_id:
                raise ValueError("source trust profile key map does not match key_id")
        return self

    @classmethod
    def load(cls, path: Path, expected_sha256: str | None = None) -> SourceTrustProfile:
        raw = path.read_bytes()
        if expected_sha256 and hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("source trust profile digest mismatch")
        return cls.model_validate_json(raw)

    @staticmethod
    def signed_payload(*, issuer: str, version: VersionCreate, source_hash: str) -> bytes:
        payload = {
            "authority": version.authority.value,
            "effective_from": (
                version.effective_from.isoformat() if version.effective_from else None
            ),
            "effective_until": (
                version.effective_until.isoformat() if version.effective_until else None
            ),
            "issuer": issuer,
            "publication_date": (
                version.publication_date.isoformat() if version.publication_date else None
            ),
            "publication_identifier": version.publication_identifier,
            "revision": version.revision,
            "source_hash": source_hash,
            "source_uri": version.source_uri,
            "supersedes_version_id": (
                str(version.supersedes_version_id) if version.supersedes_version_id else None
            ),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def verify(self, *, issuer: str, version: VersionCreate, source_hash: str) -> None:
        if not version.source_key_id or not version.source_signature_b64:
            raise ValueError("detached source signature is required")
        key = self.keys.get(version.source_key_id)
        if key is None or key.revoked:
            raise ValueError("source signing key is unknown or revoked")
        if key.issuer != issuer:
            raise ValueError("source signing key issuer mismatch")
        if key.authorities and version.authority not in key.authorities:
            raise ValueError("source signing key is not authorized for this authority class")
        reference = version.publication_date or version.effective_from or datetime.now(UTC).date()
        if key.valid_from and reference < key.valid_from:
            raise ValueError("source signature predates key validity")
        if key.valid_until and reference > key.valid_until:
            raise ValueError("source signature postdates key validity")
        try:
            signature = base64.b64decode(version.source_signature_b64, validate=True)
            public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(key.public_key_b64))
            public_key.verify(
                signature,
                self.signed_payload(issuer=issuer, version=version, source_hash=source_hash),
            )
        except (ValueError, InvalidSignature) as exc:
            raise ValueError("source signature verification failed") from exc
