"""Answer orchestration.

The order of operations is the security property here, not an implementation
detail: authorize, retrieve inside authorized tiers only, filter by review state and
validity, rank by authority, apply the evidence threshold, and only then let a
generator see anything. Every exit path records one audit event.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from korpus.application.ports import AuditSink, Clock, Generator, Retriever
from korpus.application.verification import verify
from korpus.domain.access import Principal, allowed_tiers, authorize, readable
from korpus.domain.authority import (
    conflicting_versions,
    deduplicate_by_version,
    is_current,
    may_govern,
    order_by_precedence,
)
from korpus.domain.models import (
    Answer,
    AnswerStatus,
    Citation,
    Claim,
    EvidenceSpan,
    Query,
    ReviewState,
)

ABSTENTION_TEXT = "У перевіреному корпусі недостатньо даних для надійної відповіді."
ACCESS_DENIED_TEXT = "Запитаний корпус недоступний для вашого рівня доступу."
REVIEW_TEXT = "Відповідь затримано: потрібна перевірка людиною."


@dataclass(frozen=True)
class AnswerPolicy:
    minimum_score: float = 0.72
    minimum_approved_spans: int = 1
    minimum_citation_coverage: float = 0.95
    maximum_spans: int = 8


class AnswerQuery:
    def __init__(
        self,
        retriever: Retriever,
        generator: Generator,
        audit: AuditSink,
        policy: AnswerPolicy,
        clock: Clock,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._audit = audit
        self._policy = policy
        self._clock = clock

    def eligible(self, spans: list[EvidenceSpan], now: datetime) -> list[EvidenceSpan]:
        """The product promise in one expression: approved, scored, current, governing."""
        return [
            span
            for span in spans
            if span.retrieval_score >= self._policy.minimum_score
            and span.review_state is ReviewState.APPROVED
            and is_current(span, now)
            and may_govern(span)
        ]

    async def execute(self, query: Query, principal: Principal) -> Answer:
        trace_id = uuid4()

        decision = authorize(principal, query.corpus_ids)
        if not decision.allowed:
            answer = Answer(
                trace_id=trace_id,
                status=AnswerStatus.ACCESS_DENIED,
                text=ACCESS_DENIED_TEXT,
                confidence=0,
                limitations=["Запит не виконувався: доступ до корпусу не надано."],
            )
            await self._record(
                answer,
                principal,
                retrieved=0,
                eligible=0,
                extra={
                    "denial_reason": decision.reason.value if decision.reason else None,
                    "denied_corpora": len(decision.denied_corpora),
                },
            )
            return answer

        tiers = allowed_tiers(principal.tier)
        retrieved = await self._retriever.search(query, tiers, self._policy.maximum_spans)

        # Defence in depth: a defective or swapped retriever must not widen disclosure.
        leaked = [span for span in retrieved if not readable(span, principal)]
        visible = [span for span in retrieved if readable(span, principal)]
        if leaked:
            await self._audit.record(
                "evidence.tier_violation",
                {"trace_id": str(trace_id), "spans": len(leaked)},
            )
            answer = Answer(
                trace_id=trace_id,
                status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
                text=REVIEW_TEXT,
                confidence=0,
                limitations=["Ретривер повернув матеріал поза рівнем доступу читача."],
            )
            await self._record(answer, principal, len(retrieved), 0)
            return answer

        now = self._clock.now()
        eligible = order_by_precedence(deduplicate_by_version(self.eligible(visible, now)))
        eligible = eligible[: self._policy.maximum_spans]

        if len(eligible) < self._policy.minimum_approved_spans:
            answer = Answer(
                trace_id=trace_id,
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                text=ABSTENTION_TEXT,
                confidence=0,
                limitations=["Відповідь не згенеровано без належного джерела."],
            )
            await self._record(answer, principal, len(retrieved), len(eligible))
            return answer

        citations: list[Citation] = [span.citation for span in eligible]
        try:
            claims: list[Claim] = await self._generator.compose(query, eligible)
        except Exception:  # noqa: BLE001 — a failed generator must not produce an answer
            answer = Answer(
                trace_id=trace_id,
                status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
                text=REVIEW_TEXT,
                confidence=0,
                citations=citations,
                limitations=["Генератор відповіді недоступний."],
            )
            await self._record(answer, principal, len(retrieved), len(eligible))
            return answer

        result = verify(claims, citations, eligible, principal)
        limitations = list(result.limitations)
        conflicts = conflicting_versions(eligible)
        if conflicts:
            limitations.append(
                f"Джерела рівної сили розходяться: {len(conflicts)} фрагменти."
            )

        below_threshold = result.coverage < self._policy.minimum_citation_coverage
        if result.integrity_breach or below_threshold:
            answer = Answer(
                trace_id=trace_id,
                status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
                text=REVIEW_TEXT,
                claims=claims,
                citations=citations,
                confidence=0,
                citation_coverage=result.coverage,
                limitations=limitations or ["Покриття цитатами нижче порогу."],
            )
            await self._record(answer, principal, len(retrieved), len(eligible))
            return answer

        answer = Answer(
            trace_id=trace_id,
            status=AnswerStatus.ANSWERED,
            text=" ".join(claim.text for claim in claims),
            claims=claims,
            citations=citations,
            confidence=min(span.retrieval_score for span in eligible),
            citation_coverage=result.coverage,
            limitations=limitations,
        )
        await self._record(answer, principal, len(retrieved), len(eligible))
        return answer

    async def _record(
        self,
        answer: Answer,
        principal: Principal,
        retrieved: int,
        eligible: int,
        extra: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "answer_id": str(answer.id),
            "trace_id": str(answer.trace_id),
            "subject_id": principal.subject_id,
            "principal_tier": principal.tier.value,
            "status": answer.status.value,
            "retrieved": retrieved,
            "eligible": eligible,
            "citations": len(answer.citations),
            "citation_coverage": answer.citation_coverage,
        }
        if extra:
            payload.update(extra)
        await self._audit.record("answer.completed", payload)
