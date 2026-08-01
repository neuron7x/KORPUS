from __future__ import annotations

import hashlib
from dataclasses import dataclass

from korpus.application.evidence import (
    assess_control_injection,
    contradiction_reason,
    segment_sentences,
)
from korpus.application.ports import Repository, Retriever
from korpus.application.policy import PolicyEngine
from korpus.application.retrieval import (
    AUTHORITY_PRIOR,
    RetrievalDeadlineExceeded,
    RetrievalUnavailable,
    tokenize,
)
from korpus.application.risk import QueryRisk, classify_query_risk, risk_adjusted_thresholds
from korpus.domain.models import (
    Answer,
    AnswerStatus,
    Citation,
    Claim,
    Identity,
    QueryRequest,
    RetrievedEvidence,
    SupportState,
)


@dataclass(frozen=True)
class SentenceCandidate:
    text: str
    start: int
    end: int
    query_coverage: float


def contains_control_injection(text: str) -> bool:
    return assess_control_injection(text).blocked


def sentence_candidates(text: str, query_tokens: frozenset[str]) -> list[SentenceCandidate]:
    output: list[SentenceCandidate] = []
    for sentence, start, end in segment_sentences(text):
        sentence_tokens = set(tokenize(sentence))
        coverage = len(query_tokens.intersection(sentence_tokens)) / max(len(query_tokens), 1)
        output.append(
            SentenceCandidate(
                text=sentence,
                start=start,
                end=end,
                query_coverage=coverage,
            )
        )
    return output


@dataclass(frozen=True)
class AnswerPolicy:
    minimum_score: float
    minimum_query_coverage: float
    minimum_support_score: float
    calibration_id: str
    max_claims: int = 4

    def eligible(
        self, evidence: list[RetrievedEvidence], risk: QueryRisk = QueryRisk.STANDARD
    ) -> list[RetrievedEvidence]:
        thresholds = risk_adjusted_thresholds(
            risk,
            minimum_score=self.minimum_score,
            minimum_query_coverage=self.minimum_query_coverage,
            minimum_support_score=self.minimum_support_score,
        )
        return [
            item
            for item in evidence
            if item.score >= thresholds.minimum_score
            and item.query_coverage >= thresholds.minimum_query_coverage
            and AUTHORITY_PRIOR[item.version.authority] >= thresholds.minimum_authority
            and item.version.review_state.value == "approved"
            and item.version.authority.value != "unknown"
        ]


class ExtractiveAnswerService:
    def __init__(
        self,
        repository: Repository,
        retriever: Retriever,
        policy_engine: PolicyEngine,
        answer_policy: AnswerPolicy,
    ) -> None:
        self.repository = repository
        self.retriever = retriever
        self.policy_engine = policy_engine
        self.answer_policy = answer_policy

    def execute(self, identity: Identity, query: QueryRequest) -> Answer:
        corpora = self.policy_engine.resolve_corpora(identity, query.corpus_ids)
        release_id = self.repository.corpus_release_id(identity, corpora, query.as_of)
        injection = assess_control_injection(query.text)
        if injection.blocked:
            answer = self._abstain(
                release_id,
                "query_control_injection",
                "Запит містить інструкції керування системою замість предметного питання.",
                limitations=[f"Injection signals: {', '.join(injection.reasons)}"],
            )
            self._audit(identity, query, answer, [], [], classify_query_risk(query.text))
            return answer

        risk = classify_query_risk(query.text)
        try:
            retrieved = self.retriever.search(identity, query.text, corpora, query.as_of)
        except RetrievalDeadlineExceeded:
            answer = self._abstain(
                release_id,
                "retrieval_deadline_exceeded",
                "Пошук не завершився у межах операційного бюджету; відповідь зупинено.",
            )
            self._audit(identity, query, answer, [], [], risk)
            return answer
        except RetrievalUnavailable:
            answer = self._abstain(
                release_id,
                "retrieval_dependency_unavailable",
                "Обов’язковий пошуковий контур недоступний; відповідь зупинено без слабшого fallback.",
            )
            self._audit(identity, query, answer, [], [], risk)
            return answer
        eligible = self.answer_policy.eligible(retrieved, risk)
        if not eligible:
            answer = self._abstain(
                release_id,
                "retrieval_gate_failed",
                "У чинному перевіреному корпусі недостатньо доказів для надійної відповіді.",
                max((item.score for item in retrieved), default=0.0),
            )
            self._audit(identity, query, answer, retrieved, eligible, risk)
            return answer

        thresholds = risk_adjusted_thresholds(
            risk,
            minimum_score=self.answer_policy.minimum_score,
            minimum_query_coverage=self.answer_policy.minimum_query_coverage,
            minimum_support_score=self.answer_policy.minimum_support_score,
        )
        query_tokens = frozenset(tokenize(query.text))
        claims: list[Claim] = []
        citations: list[Citation] = []
        seen_sentences: set[str] = set()
        covered_tokens: set[str] = set()

        for item in eligible:
            candidates = sorted(
                sentence_candidates(item.span.text, query_tokens),
                key=lambda candidate: (-candidate.query_coverage, candidate.start),
            )
            candidate = next(
                (
                    current
                    for current in candidates
                    if current.text not in seen_sentences
                    and not contains_control_injection(current.text)
                ),
                None,
            )
            if candidate is None or candidate.query_coverage < thresholds.minimum_query_coverage:
                continue
            # The claim is a byte-for-byte extract from the cited span. Support is therefore
            # exact; relevance remains a separate query-coverage gate.
            support_score = 1.0
            if support_score < thresholds.minimum_support_score:
                continue
            claims.append(
                Claim(
                    text=candidate.text,
                    evidence_span_ids=(item.span.id,),
                    support_state=SupportState.EXTRACTIVE,
                    support_score=support_score,
                    query_coverage=candidate.query_coverage,
                )
            )
            quote_hash = hashlib.sha256(candidate.text.encode("utf-8")).hexdigest()
            citations.append(
                Citation(
                    document_id=item.document.id,
                    version_id=item.version.id,
                    span_id=item.span.id,
                    title=item.document.canonical_title,
                    revision=item.version.revision,
                    page=item.span.page,
                    section=item.span.section,
                    quote=candidate.text,
                    quote_start=candidate.start,
                    quote_end=candidate.end,
                    quote_hash=quote_hash,
                    source_uri=item.version.source_uri,
                    source_hash=item.version.source_hash,
                )
            )
            seen_sentences.add(candidate.text)
            covered_tokens.update(set(tokenize(candidate.text)).intersection(query_tokens))
            if len(claims) >= self.answer_policy.max_claims:
                break

        query_coverage = len(covered_tokens) / max(len(query_tokens), 1)
        evidence_coverage = len(citations) / max(len(claims), 1) if claims else 0.0
        if not claims or query_coverage < thresholds.minimum_query_coverage:
            answer = self._abstain(
                release_id,
                "claim_support_gate_failed",
                "Джерела знайдено, але вони не підтримують конкретну відповідь на запит.",
                max((item.score for item in eligible), default=0.0),
                query_coverage=query_coverage,
            )
        else:
            contradiction = self._find_contradiction(claims)
            if contradiction is not None:
                answer = Answer(
                    status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
                    text="Затверджені джерела містять взаємно несумісні твердження; автоматичну відповідь зупинено.",
                    claims=claims,
                    citations=citations,
                    retrieval_score=max(item.score for item in eligible),
                    evidence_coverage=evidence_coverage,
                    query_coverage=query_coverage,
                    decision_reason="contradictory_authoritative_evidence",
                    calibration_id=self.answer_policy.calibration_id,
                    limitations=[f"Conflict: {contradiction}"],
                    corpus_release=release_id,
                )
            else:
                answer = Answer(
                    status=AnswerStatus.ANSWERED,
                    text="\n\n".join(claim.text for claim in claims),
                    claims=claims,
                    citations=citations,
                    retrieval_score=max(item.score for item in eligible),
                    evidence_coverage=evidence_coverage,
                    query_coverage=query_coverage,
                    decision_reason="extractive_claims_passed_calibrated_gates",
                    calibration_id=self.answer_policy.calibration_id,
                    limitations=[
                        "Відповідь екстрактивна: система не додає фактів поза точними цитованими реченнями.",
                        "Retrieval score є ranking utility, а не ймовірністю істинності.",
                    ],
                    corpus_release=release_id,
                )
        self._audit(identity, query, answer, retrieved, eligible, risk)
        return answer

    @staticmethod
    def _find_contradiction(claims: list[Claim]) -> str | None:
        for left_index, left in enumerate(claims):
            for right in claims[left_index + 1 :]:
                reason = contradiction_reason(left.text, right.text)
                if reason is not None:
                    return reason
        return None

    def _abstain(
        self,
        release_id: str,
        reason: str,
        text: str,
        retrieval_score: float = 0.0,
        *,
        query_coverage: float = 0.0,
        limitations: list[str] | None = None,
    ) -> Answer:
        return Answer(
            status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            text=text,
            retrieval_score=retrieval_score,
            evidence_coverage=0.0,
            query_coverage=query_coverage,
            decision_reason=reason,
            calibration_id=self.answer_policy.calibration_id,
            limitations=["Генерацію зупинено fail-closed.", *(limitations or [])],
            corpus_release=release_id,
        )

    def _audit(
        self,
        identity: Identity,
        query: QueryRequest,
        answer: Answer,
        retrieved: list[RetrievedEvidence],
        eligible: list[RetrievedEvidence],
        risk: QueryRisk = QueryRisk.STANDARD,
    ) -> None:
        self.repository.append_audit(
            identity,
            "answer.completed",
            "answer",
            str(answer.id),
            {
                "status": answer.status.value,
                "decision_reason": answer.decision_reason,
                "query_hash": hashlib.sha256(query.text.encode("utf-8")).hexdigest(),
                "requested_corpora": query.corpus_ids,
                "retrieved": len(retrieved),
                "eligible": len(eligible),
                "citation_count": len(answer.citations),
                "evidence_coverage": answer.evidence_coverage,
                "query_coverage": answer.query_coverage,
                "retrieval_score_kind": answer.retrieval_score_kind,
                "calibration_id": answer.calibration_id,
                "corpus_release": answer.corpus_release,
                "query_risk": risk.value,
            },
        )
