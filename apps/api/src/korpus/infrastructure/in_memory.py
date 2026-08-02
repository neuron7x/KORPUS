"""In-process adapters.

These are the development and test implementations of the ports. They are honest
stubs: each one refuses to do the part it cannot do, instead of approximating it.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from uuid import UUID

from korpus.domain.access import Principal
from korpus.domain.models import AccessTier, Claim, EvidenceSpan, Query


class InMemoryRetriever:
    """Returns pre-supplied spans, tier-filtered. Ignores relevance on purpose."""

    def __init__(self, spans: list[EvidenceSpan] | None = None) -> None:
        self.spans = list(spans or [])

    async def search(
        self,
        query: Query,
        allowed_tiers: frozenset[AccessTier],
        allowed_corpora: frozenset[UUID],
        limit: int = 8,
    ) -> list[EvidenceSpan]:
        del query
        visible = [
            span
            for span in self.spans
            if span.access_tier in allowed_tiers and span.corpus_id in allowed_corpora
        ]
        ranked = sorted(
            visible, key=lambda item: (-item.retrieval_score, str(item.chunk_id))
        )
        return ranked[:limit]


class EvidenceBoundStubGenerator:
    """Emits one claim per evidence span, quoting it and citing its index.

    This cannot hallucinate, and it is not intelligence: it is the floor that a
    model-backed generator has to beat on the eval set before it may replace it.
    """

    async def compose(self, query: Query, evidence: list[EvidenceSpan]) -> list[Claim]:
        del query
        return [
            Claim(text=span.citation.quote, citation_indexes=(index,))
            for index, span in enumerate(evidence)
        ]


class InMemoryAuditSink:
    """Bounded on purpose.

    An unbounded list on a process-global sink is a memory leak that any
    unauthenticated caller can drive, and it retains subject identifiers with no
    eviction path. The real sink is durable and append-only; this one forgets.
    """

    def __init__(self, capacity: int = 1000) -> None:
        self.events: deque[tuple[str, dict[str, object]]] = deque(maxlen=capacity)

    async def record(self, event: str, payload: dict[str, object]) -> None:
        self.events.append((event, payload))


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Deterministic clock. Validity and supersession are testable without waiting."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class StaticPrincipalResolver:
    """Development resolver: a token table, nothing more.

    It is not an authentication system and never claims to be one. `main.py` refuses
    to start with this resolver in production, so the absence of real identity is a
    startup failure rather than a silent authorization hole.
    """

    development_only = True

    def __init__(
        self,
        table: dict[str, Principal] | None = None,
        anonymous: Principal | None = None,
    ) -> None:
        self._table = dict(table or {})
        # An anonymous caller holds whatever grant the deployment chose to give it —
        # by default nothing, so a missing wiring step denies rather than opens.
        self._anonymous = anonymous or Principal(
            subject_id="anonymous", tier=AccessTier.PUBLIC
        )

    async def resolve(self, credentials: str | None) -> Principal:
        if credentials is None:
            return self._anonymous
        return self._table.get(credentials, self._anonymous)
