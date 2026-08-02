from datetime import datetime
from typing import Protocol

from korpus.domain.access import Principal
from korpus.domain.models import AccessTier, Claim, EvidenceSpan, Query


class Retriever(Protocol):
    async def search(
        self,
        query: Query,
        allowed_tiers: frozenset[AccessTier],
        limit: int = 8,
    ) -> list[EvidenceSpan]:
        """Search inside the authorized tiers only.

        `allowed_tiers` is an argument rather than a post-filter so an adapter backed
        by separate per-tier indexes can honour it at the index boundary (ADR-0004).
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
