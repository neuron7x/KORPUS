from __future__ import annotations

from dataclasses import dataclass

from korpus.domain.models import DocumentRecord, Identity


class AuthorizationError(PermissionError):
    pass


class UnauthorizedCorporaError(AuthorizationError):
    """One requested corpus the reader does not hold denies the whole request.

    The refusal existed but carried only a sentence. A reader could not tell which of
    the corpora they named was refused, and the set was a `frozenset`, so the order in
    which they asked was lost before anything could report it. Both matter: the reason
    is what an operator acts on, and the order is what the reader recognises.
    """

    reason = "requested_corpora_not_held"

    def __init__(self, requested: list[str], denied: list[str]) -> None:
        self.requested = list(requested)
        self.denied = list(denied)
        super().__init__(f"requested corpora not held: {', '.join(denied)}")


#: Every permission this system checks, whether or not a role other than `admin` holds it.
#: `admin` holds `*` and needs no entry, which is exactly how `account:manage` came to be
#: required by a route and absent from the table the browser reads: the console decided
#: which tab to show from that table, so a `security-officer` role granted the permission
#: without the wildcard would have been allowed by the API and shown nothing.
#:
#: Named here so the set is enumerable. `test_permission_contract.py` compares it against
#: what the API actually requires, in both directions.
KNOWN_PERMISSIONS: frozenset[str] = frozenset(
    {
        "answer:read",
        "document:list",
        "document:ingest",
        "document:review",
        "document:review_metadata",
        "document:approve",
        "audit:read",
        "audit:verify",
        "training:manage",
        "account:manage",
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "user": frozenset({"answer:read", "document:list"}),
    "instructor": frozenset({"answer:read", "document:list", "training:manage"}),
    "curator": frozenset(
        {"answer:read", "document:list", "document:ingest", "document:review_metadata"}
    ),
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
        denied = [corpus for corpus in requested if corpus not in identity.corpora]
        if denied:
            raise UnauthorizedCorporaError(requested, denied)
        return frozenset(requested)
