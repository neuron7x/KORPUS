from datetime import datetime
from typing import Protocol
from uuid import UUID

from korpus.domain.access import Principal
from korpus.domain.models import AccessTier, Claim, EvidenceSpan, Query


class Retriever(Protocol):
    async def search(
        self,
        query: Query,
        allowed_tiers: frozenset[AccessTier],
        allowed_corpora: frozenset[UUID],
        limit: int = 8,
    ) -> list[EvidenceSpan]:
        """Search inside the authorized tiers and corpora only.

        Both bounds are arguments rather than post-filters so an adapter backed by
        separate per-tier indexes or per-corpus buckets can honour them at the index
        boundary (ADR-0004). An empty corpus set means an empty result — never "all".
        """
        ...


class Generator(Protocol):
    async def compose(self, query: Query, evidence: list[EvidenceSpan]) -> list[Claim]:
        """Return claims that reference `evidence` by index.

        The port returns claims, not prose: an interface that can only emit indexed
        claims cannot express an uncited sentence.
        """
        ...


class AuditSink(Protocol):
    async def record(self, event: str, payload: dict[str, object]) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime:
        """Injected so validity and supersession are testable without waiting."""
        ...


class PrincipalResolver(Protocol):
    async def resolve(self, credentials: str | None) -> Principal:
        """Derive the caller server-side. Must fail closed on absent credentials."""
        ...
