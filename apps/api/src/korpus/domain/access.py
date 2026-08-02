"""Access decisions taken before retrieval (ADR-0004).

Post-generation redaction cannot undo disclosure to a model or to a log, so the
authorization boundary is placed in front of the index, not behind the generator.
Everything in this module is deterministic code with no model in the path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from korpus.domain.models import AccessTier, EvidenceSpan

# Total order over tiers. A principal may read its own tier and everything below it.
TIER_ORDER: dict[AccessTier, int] = {
    AccessTier.PUBLIC: 0,
    AccessTier.AUTHENTICATED: 1,
    AccessTier.REVIEWED: 2,
    AccessTier.RESTRICTED: 3,
}


class DenialReason(StrEnum):
    CORPUS_NOT_AUTHORIZED = "corpus_not_authorized"
    TIER_INSUFFICIENT = "tier_insufficient"


@dataclass(frozen=True)
class Principal:
    """Server-side identity. Never constructed from client-supplied fields."""

    subject_id: str
    tier: AccessTier = AccessTier.PUBLIC
    authorized_corpora: frozenset[UUID] = frozenset()


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: DenialReason | None = None
    denied_corpora: tuple[UUID, ...] = ()
    # The corpora this request may search. Empty means: nothing is searchable, which
    # is the correct answer for a principal holding no grant.
    scope: frozenset[UUID] = frozenset()


def allowed_tiers(principal: AccessTier) -> frozenset[AccessTier]:
    """Tiers a principal may read. Unknown tiers are excluded, never defaulted in."""
    ceiling = TIER_ORDER[principal]
    return frozenset(tier for tier, rank in TIER_ORDER.items() if rank <= ceiling)


def authorize(principal: Principal, requested_corpora: list[UUID]) -> AccessDecision:
    """Decide before any index is touched.

    An explicitly requested corpus that the principal does not hold is a denial, not
    a silent empty result: the user asked a direct question and deserves a direct no.

    Omitting the field is NOT a wildcard. The search scope of a request that names no
    corpus is the principal's own grant — otherwise the whole authorization model
    would be opt-in, enforced only against callers polite enough to declare what they
    are reaching for.
    """
    denied = tuple(c for c in requested_corpora if c not in principal.authorized_corpora)
    if denied:
        return AccessDecision(
            allowed=False,
            reason=DenialReason.CORPUS_NOT_AUTHORIZED,
            denied_corpora=denied,
        )
    scope = frozenset(requested_corpora) if requested_corpora else principal.authorized_corpora
    return AccessDecision(allowed=True, scope=scope)


def in_scope(span: EvidenceSpan, scope: frozenset[UUID]) -> bool:
    """Redundant corpus check over whatever the retriever returned, mirroring `readable`."""
    return span.corpus_id in scope


def readable(span: EvidenceSpan, principal: Principal) -> bool:
    """Second, redundant check applied to whatever the retriever returned.

    The retriever is already told which tiers to search. This function assumes the
    retriever may be wrong — a defective or replaced adapter must not be able to
    widen disclosure on its own.
    """
    return TIER_ORDER[span.access_tier] <= TIER_ORDER[principal.tier]
