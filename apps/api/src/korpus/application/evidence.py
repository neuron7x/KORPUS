"""The evidence gate, shared by every caller that touches the corpus.

Answering and browsing are different products with one identical obligation: they
must not show a reader anything the reader may not see. Duplicating that sequence
into two services is how the two drift apart, and the one nobody reviews becomes the
way in. It exists once, here, and both call it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from korpus.domain.access import (
    AccessDecision,
    Principal,
    allowed_tiers,
    authorize,
    in_scope,
    readable,
)
from korpus.domain.authority import (
    deduplicate_by_version,
    is_current,
    may_govern,
    order_by_precedence,
)
from korpus.domain.models import EvidenceSpan, Query, ReviewState


@dataclass(frozen=True)
class EvidenceLimits:
    """The knobs that decide how much is looked at and how much is used."""

    minimum_score: float = 0.72
    maximum_spans: int = 8
    candidate_multiplier: int = 8


@dataclass(frozen=True)
class Gathered:
    """What the gate produced, and everything a caller needs to explain it."""

    decision: AccessDecision
    spans: list[EvidenceSpan]
    retrieved: int
    leaked: int

    @property
    def denied(self) -> bool:
        return not self.decision.allowed

    @property
    def breached(self) -> bool:
        """The retriever returned material outside the bounds it was given."""
        return self.leaked > 0


def eligible(
    spans: list[EvidenceSpan], now: datetime, minimum_score: float
) -> list[EvidenceSpan]:
    """The product promise in one expression: approved, scored, current, governing."""
    return [
        span
        for span in spans
        if span.retrieval_score >= minimum_score
        and span.review_state is ReviewState.APPROVED
        and is_current(span, now)
        and may_govern(span)
    ]


async def gather(
    retriever: object,
    query: Query,
    principal: Principal,
    limits: EvidenceLimits,
    now: datetime,
) -> Gathered:
    """Authorize, retrieve inside the authorized bounds, re-check, filter, rank.

    The order is the security property. Nothing below this function is allowed to
    widen it, and nothing above it may skip a step by calling the retriever directly.
    """
    decision = authorize(principal, query.corpus_ids)
    if not decision.allowed:
        return Gathered(decision=decision, spans=[], retrieved=0, leaked=0)

    retrieved = await retriever.search(  # type: ignore[attr-defined]
        query,
        allowed_tiers(principal.tier),
        decision.scope,
        limits.maximum_spans * limits.candidate_multiplier,
    )

    # Defence in depth: a defective or swapped adapter must not widen disclosure.
    leaked = [
        span
        for span in retrieved
        if not readable(span, principal) or not in_scope(span, decision.scope)
    ]
    if leaked:
        return Gathered(
            decision=decision, spans=[], retrieved=len(retrieved), leaked=len(leaked)
        )

    ranked = order_by_precedence(
        deduplicate_by_version(eligible(retrieved, now, limits.minimum_score))
    )
    return Gathered(
        decision=decision,
        spans=ranked[: limits.maximum_spans],
        retrieved=len(retrieved),
        leaked=0,
    )
