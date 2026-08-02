"""Answer orchestration.

The order of operations is the security property here, not an implementation
detail: authorize, retrieve inside authorized tiers only, filter by review state and
validity, rank by authority, apply the evidence threshold, and only then let a
generator see anything. Every exit path records one audit event.
"""

import asyncio
from dataclasses import dataclass
from uuid import uuid4

from korpus.application.evidence import EvidenceLimits, gather
from korpus.application.ports import AuditSink, Clock, Generator, Retriever
from korpus.application.verification import verify
from korpus.domain.access import Principal
from korpus.domain.authority import conflicting_versions
from korpus.domain.models import Answer, AnswerStatus, Citation, Claim, Query

ABSTENTION_TEXT = "У перевіреному корпусі недостатньо даних для надійної відповіді."
ACCESS_DENIED_TEXT = "Запитаний корпус недоступний для вашого рівня доступу."
REVIEW_TEXT = "Відповідь затримано: потрібна перевірка людиною."


@dataclass(frozen=True)
class AnswerPolicy:
    minimum_score: float = 0.72
    minimum_approved_spans: int = 1
    maximum_spans: int = 8
    generator_timeout_seconds: float = 30.0
    # Candidates are fetched wider than the answer, because eligibility is decided
    # here and not in the index: asking for exactly `maximum_spans` lets unapproved,
    # superseded or adversary-authored chunks with a better lexical match crowd the
    # governing source out of the candidate set before it is ever examined.
    candidate_multiplier: int = 8


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

    @property
    def limits(self) -> EvidenceLimits:
        return EvidenceLimits(
            minimum_score=self._policy.minimum_score,
            maximum_spans=self._policy.maximum_spans,
            candidate_multiplier=self._policy.candidate_multiplier,
        )

    async def execute(self, query: Query, principal: Principal) -> Answer:
        trace_id = uuid4()

        gathered = await gather(
            self._retriever, query, principal, self.limits, self._clock.now()
        )
        decision = gathered.decision
        if gathered.denied:
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

        if gathered.breached:
            await self._audit.record(
                "evidence.tier_violation",
                {"trace_id": str(trace_id), "spans": gathered.leaked},
            )
            answer = Answer(
                trace_id=trace_id,
                status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
                text=REVIEW_TEXT,
                confidence=0,
                limitations=["Ретривер повернув матеріал поза рівнем доступу читача."],
            )
            await self._record(answer, principal, gathered.retrieved, 0)
            return answer

        eligible = gathered.spans
        if len(eligible) < self._policy.minimum_approved_spans:
            answer = Answer(
                trace_id=trace_id,
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                text=ABSTENTION_TEXT,
                confidence=0,
                limitations=["Відповідь не згенеровано без належного джерела."],
            )
            await self._record(answer, principal, gathered.retrieved, len(eligible))
            return answer

        citations: list[Citation] = [span.citation for span in eligible]
        try:
            async with asyncio.timeout(self._policy.generator_timeout_seconds):
                claims: list[Claim] = await self._generator.compose(query, eligible)
        except Exception:  # noqa: BLE001 — a failed or hanging generator must not answer
            answer = Answer(
                trace_id=trace_id,
                status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
                text=REVIEW_TEXT,
                confidence=0,
                limitations=["Генератор відповіді недоступний."],
            )
            await self._record(answer, principal, gathered.retrieved, len(eligible))
            return answer

        result = verify(claims, citations, eligible, principal)
        limitations = list(result.limitations)
        conflicts = conflicting_versions(eligible)
        if conflicts:
            limitations.append(
                f"Джерела рівної сили розходяться: {len(conflicts)} фрагменти."
            )

        # Any unsupported claim blocks. There is deliberately no ratio to tune: a
        # 0.95 floor let one uncited sentence in twenty ship inside an `answered`
        # response, and a threshold that cannot be set to anything but 1.0 without
        # breaking the promise is not a setting, it is a hole with a dial on it.
        if result.integrity_breach or result.unsupported or result.empty:
            # A held answer returns no evidence to the caller. The reviewer reads it
            # from the audit trail; shipping the quotes with the refusal would hand
            # over exactly the material the hold exists to withhold.
            answer = Answer(
                trace_id=trace_id,
                status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
                text=REVIEW_TEXT,
                confidence=0,
                citation_coverage=result.coverage,
                limitations=limitations or ["Відповідь не пройшла перевірку посилань."],
            )
            await self._record(answer, principal, gathered.retrieved, len(eligible))
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
        await self._record(answer, principal, gathered.retrieved, len(eligible))
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
