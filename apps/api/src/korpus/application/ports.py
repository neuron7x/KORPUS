from typing import Protocol

from korpus.domain.models import EvidenceSpan, Query


class Retriever(Protocol):
    async def search(self, query: Query, limit: int = 8) -> list[EvidenceSpan]: ...


class Generator(Protocol):
    async def answer(self, query: Query, evidence: list[EvidenceSpan]) -> str: ...


class AuditSink(Protocol):
    async def record(self, event: str, payload: dict[str, object]) -> None: ...

