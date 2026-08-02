from dataclasses import dataclass

from korpus.application.ports import AuditSink, Generator, Retriever
from korpus.domain.models import Answer, AnswerStatus, EvidenceSpan, Query, ReviewState


@dataclass(frozen=True)
class AnswerPolicy:
    minimum_score: float = 0.72
    minimum_approved_spans: int = 1

    def eligible(self, spans: list[EvidenceSpan]) -> list[EvidenceSpan]:
        return [
            span
            for span in spans
            if span.retrieval_score >= self.minimum_score
            and span.review_state is ReviewState.APPROVED
        ]


class AnswerQuery:
    def __init__(
        self,
        retriever: Retriever,
        generator: Generator,
        audit: AuditSink,
        policy: AnswerPolicy,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._audit = audit
        self._policy = policy

    async def execute(self, query: Query) -> Answer:
        retrieved = await self._retriever.search(query)
        evidence = self._policy.eligible(retrieved)
        if len(evidence) < self._policy.minimum_approved_spans:
            answer = Answer(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                text="У перевіреному корпусі недостатньо даних для надійної відповіді.",
                confidence=0,
                limitations=["Відповідь не згенеровано без належного джерела."],
            )
        else:
            text = await self._generator.answer(query, evidence)
            answer = Answer(
                status=AnswerStatus.ANSWERED,
                text=text,
                citations=[span.citation for span in evidence],
                confidence=min(span.retrieval_score for span in evidence),
            )
        await self._audit.record(
            "answer.completed",
            {
                "answer_id": str(answer.id),
                "status": answer.status.value,
                "retrieved": len(retrieved),
                "eligible": len(evidence),
            },
        )
        return answer

