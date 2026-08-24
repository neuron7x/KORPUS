"""Emergency access that costs something to use, and cannot be used quietly.

IAM-008. There was no path for "the reviewer with the clearance is unreachable and a
soldier needs the order now", which means the real path was somebody's admin token and no
record that it happened. A break-glass control that does not exist is not absent; it is
informal.

Four properties, and the third is the one that makes the others matter:

  two people      one person cannot grant themselves emergency access. The approver is a
                  second named subject with the authority to approve, and it may not be
                  the requester — the same rule the review flow already applies to
                  approving a document, for the same reason.
  bounded         a grant expires. An emergency that lasts a week is not an emergency,
                  it is an entitlement nobody reviewed.
  loud            the grant, its reason, both names and every action taken under it enter
                  the audit chain as break-glass. A control whose use looks like ordinary
                  use is a control that gets used ordinarily.
  narrow          it widens clearance and corpus reach. It cannot grant a role the
                  entitlement profile does not already define, and it never grants
                  approval authority: an emergency is a reason to *read* something, and a
                  document approved under duress is the failure this system exists to
                  prevent.

What stays external: a JIT/PAM system holds the credential and issues it, and the
immutable session log is a recording of what the operator did at the terminal. This is the
decision and the record of it, not the vault.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from korpus.domain.models import AccessTier, Identity

#: Long enough to read an order and act on it, short enough that nobody plans around it.
DEFAULT_GRANT_MINUTES = 30
MAX_GRANT_MINUTES = 240

#: Never granted, whatever the emergency. Approval is a person taking responsibility for a
#: document entering the answerable set; a signature made under duress, by someone the
#: reviewer registry does not know, is the thing the registry exists to make impossible.
FORBIDDEN_ROLES = frozenset({"reviewer", "curator", "admin"})

#: A reason is not a formality. It is what an investigator reads first, and "urgent" tells
#: them nothing, so the shape is checked even though the content cannot be.
MIN_REASON_CHARS = 24


class BreakGlassRefused(PermissionError):
    """Raised when a grant would violate a property above. The message names which."""


@dataclass(frozen=True)
class BreakGlassGrant:
    """One emergency elevation, with everything an investigator needs to judge it."""

    id: UUID
    requester: str
    approver: str
    reason: str
    clearance: AccessTier
    corpora: frozenset[str]
    granted_at: datetime
    expires_at: datetime

    def active_at(self, moment: datetime) -> bool:
        return self.granted_at <= moment < self.expires_at

    def elevate(self, identity: Identity, moment: datetime) -> Identity:
        """The requester's identity, widened, for as long as the grant lasts.

        Roles are copied unchanged. Emergency access is a reason to read something, and a
        role is the authority to *do* something; widening one to solve the other is how a
        break-glass path becomes a way to approve documents at three in the morning.
        """
        if identity.subject != self.requester:
            raise BreakGlassRefused("a grant elevates the subject it was issued to, nobody else")
        if not self.active_at(moment):
            raise BreakGlassRefused("the grant has expired")
        return identity.model_copy(
            update={
                "clearance": self.clearance,
                "corpora": frozenset(identity.corpora | self.corpora),
            }
        )

    def as_audit_record(self) -> dict[str, Any]:
        return {
            "grant_id": str(self.id),
            "requester": self.requester,
            "approver": self.approver,
            "reason": self.reason,
            "clearance": int(self.clearance),
            "corpora": sorted(self.corpora),
            "granted_at": self.granted_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "interpretation": (
                "Emergency elevation, approved by a second named subject. Every action "
                "taken under it is recorded as break-glass rather than as ordinary use: a "
                "control whose use looks ordinary is a control that gets used ordinarily."
            ),
        }


def grant(
    *,
    requester: Identity,
    approver: Identity,
    reason: str,
    clearance: AccessTier,
    corpora: frozenset[str],
    minutes: int = DEFAULT_GRANT_MINUTES,
    now: datetime | None = None,
) -> BreakGlassGrant:
    """Issue a grant, or refuse and say which property would have been broken."""
    moment = now or datetime.now(UTC)

    if approver.subject == requester.subject:
        raise BreakGlassRefused("break-glass requires a second person; this is one person twice")
    if "admin" not in approver.roles and "auditor" not in approver.roles:
        raise BreakGlassRefused("the approver holds no authority to approve an elevation")
    if approver.clearance < clearance:
        # Otherwise the emergency path grants more than the person approving it could see,
        # which makes the approval a rubber stamp on something unread.
        raise BreakGlassRefused("the approver cannot grant a clearance above their own")
    if len(reason.strip()) < MIN_REASON_CHARS:
        raise BreakGlassRefused(
            f"a reason under {MIN_REASON_CHARS} characters is a formality, not a reason"
        )
    if not 1 <= minutes <= MAX_GRANT_MINUTES:
        raise BreakGlassRefused(f"a grant must expire within {MAX_GRANT_MINUTES} minutes")
    forbidden = requester.roles & FORBIDDEN_ROLES
    if forbidden:
        # Refused rather than silently narrowed: someone asking to break glass while
        # holding approval authority is a situation a human should look at.
        raise BreakGlassRefused(
            f"break-glass does not extend to approval authority: {sorted(forbidden)}"
        )
    if not corpora:
        raise BreakGlassRefused("a grant that widens nothing is a record of nothing")

    return BreakGlassGrant(
        id=uuid4(),
        requester=requester.subject,
        approver=approver.subject,
        reason=reason.strip(),
        clearance=clearance,
        corpora=frozenset(corpora),
        granted_at=moment,
        expires_at=moment + timedelta(minutes=minutes),
    )
