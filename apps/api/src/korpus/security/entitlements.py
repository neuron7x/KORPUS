from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from korpus.domain.models import CORPUS_ID_PATTERN, ROLE_PATTERN, AccessTier, Identity


class EntitlementGrant(BaseModel):
    roles: frozenset[str] = Field(default_factory=frozenset, max_length=32)
    clearance: AccessTier = AccessTier.PUBLIC
    corpora: frozenset[str] = Field(default_factory=lambda: frozenset({"public"}), max_length=64)
    compartments: frozenset[str] = Field(default_factory=frozenset, max_length=64)

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, values: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(value.strip().lower() for value in values)
        if any(not ROLE_PATTERN.fullmatch(value) for value in normalized):
            raise ValueError("invalid entitlement role")
        return normalized

    @field_validator("corpora", "compartments")
    @classmethod
    def validate_names(cls, values: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(value.strip().lower() for value in values)
        if any(not CORPUS_ID_PATTERN.fullmatch(value) for value in normalized):
            raise ValueError("invalid entitlement scope")
        return normalized


class EntitlementProfile(BaseModel):
    """Server-controlled identity projection.

    OIDC tokens authenticate subjects and groups. They do not directly grant application
    roles, clearance, corpora, or compartments. Those attributes are projected through
    this content-addressed profile, so an IdP claim-mapping mistake cannot silently grant
    application privileges.
    """

    schema_version: int = Field(default=1, ge=1, le=1)
    profile_id: str = Field(min_length=3, max_length=120)
    issuer: str = Field(min_length=3, max_length=500)
    audience: str = Field(min_length=1, max_length=500)
    default: EntitlementGrant = Field(default_factory=EntitlementGrant)
    subjects: dict[str, EntitlementGrant] = Field(default_factory=dict)
    groups: dict[str, EntitlementGrant] = Field(default_factory=dict)
    deny_subjects: frozenset[str] = Field(default_factory=frozenset)

    @model_validator(mode="after")
    def validate_profile(self) -> EntitlementProfile:
        overlap = set(self.subjects).intersection(self.deny_subjects)
        if overlap:
            raise ValueError("denied subjects cannot have explicit grants")
        return self

    @classmethod
    def load(cls, path: Path, expected_sha256: str | None = None) -> EntitlementProfile:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError("entitlement profile digest mismatch")
        return cls.model_validate_json(raw)

    def canonical_digest(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _merge(base: EntitlementGrant, extra: EntitlementGrant) -> EntitlementGrant:
        return EntitlementGrant(
            roles=base.roles.union(extra.roles),
            clearance=max(base.clearance, extra.clearance),
            corpora=base.corpora.union(extra.corpora),
            compartments=base.compartments.union(extra.compartments),
        )

    def resolve(self, claims: dict[str, Any]) -> Identity:
        subject = str(claims.get("sub", "")).strip()
        if not subject or subject in self.deny_subjects:
            raise PermissionError("subject has no active entitlement")
        if claims.get("iss") != self.issuer:
            raise PermissionError("entitlement issuer mismatch")
        audiences = claims.get("aud", [])
        audience_values = {audiences} if isinstance(audiences, str) else set(audiences)
        if self.audience not in audience_values:
            raise PermissionError("entitlement audience mismatch")

        grant = self.default
        raw_groups = claims.get("groups", [])
        group_values = [raw_groups] if isinstance(raw_groups, str) else list(raw_groups)
        for group in sorted(str(value) for value in group_values):
            mapped = self.groups.get(group)
            if mapped is not None:
                grant = self._merge(grant, mapped)
        subject_grant = self.subjects.get(subject)
        if subject_grant is not None:
            grant = self._merge(grant, subject_grant)
        if not grant.roles:
            raise PermissionError("subject has no application roles")
        return Identity(
            subject=subject,
            roles=grant.roles,
            clearance=grant.clearance,
            corpora=grant.corpora,
            compartments=grant.compartments,
        )
