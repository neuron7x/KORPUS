from __future__ import annotations

from dataclasses import dataclass

from korpus.domain.models import DocumentRecord, Identity


class AuthorizationError(PermissionError):
    pass


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "user": frozenset({"answer:read", "document:list"}),
    "instructor": frozenset({"answer:read", "document:list", "training:manage"}),
    "curator": frozenset({"answer:read", "document:list", "document:ingest", "document:review_metadata"}),
    "reviewer": frozenset({"answer:read", "document:list", "document:review", "document:approve"}),
    "auditor": frozenset({"audit:read", "audit:verify", "document:list"}),
    "admin": frozenset({"*"}),
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PolicyEngine:
    def permissions(self, identity: Identity) -> frozenset[str]:
        permissions: set[str] = set()
        for role in identity.roles:
            permissions.update(ROLE_PERMISSIONS.get(role, ()))
        return frozenset(permissions)

    def require(self, identity: Identity, permission: str) -> None:
        permissions = self.permissions(identity)
        if "*" not in permissions and permission not in permissions:
            raise AuthorizationError(f"missing permission: {permission}")

    def can_access_document(self, identity: Identity, document: DocumentRecord) -> PolicyDecision:
        if identity.clearance < document.access_tier:
            return PolicyDecision(False, "clearance below document access tier")
        if document.classification.minimum_tier > identity.clearance:
            return PolicyDecision(False, "clearance below classification minimum")
        if document.corpus_id not in identity.corpora:
            return PolicyDecision(False, "corpus not assigned to identity")
        if not document.compartments.issubset(identity.compartments):
            return PolicyDecision(False, "need-to-know compartment not assigned")
        return PolicyDecision(True, "authorized")

    def resolve_corpora(self, identity: Identity, requested: list[str]) -> frozenset[str]:
        self.require(identity, "answer:read")
        if not requested:
            return identity.corpora
        requested_set = frozenset(requested)
        unauthorized = requested_set.difference(identity.corpora)
        if unauthorized:
            raise AuthorizationError("requested corpora exceed identity authorization")
        return requested_set
