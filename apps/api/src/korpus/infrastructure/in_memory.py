from korpus.domain.models import EvidenceSpan, Query


class InMemoryRetriever:
    def __init__(self, spans: list[EvidenceSpan] | None = None) -> None:
        self.spans = spans or []

    async def search(self, query: Query, limit: int = 8) -> list[EvidenceSpan]:
        del query
        return sorted(self.spans, key=lambda item: item.retrieval_score, reverse=True)[:limit]


class EvidenceBoundStubGenerator:
    async def answer(self, query: Query, evidence: list[EvidenceSpan]) -> str:
        del query
        return " ".join(span.citation.quote for span in evidence)


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    async def record(self, event: str, payload: dict[str, object]) -> None:
        self.events.append((event, payload))

