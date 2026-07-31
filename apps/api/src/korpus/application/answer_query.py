from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from korpus.application.ports import Repository, Retriever
from korpus.application.policy import PolicyEngine
from korpus.application.retrieval import (
    AUTHORITY_PRIOR,
    RetrievalDeadlineExceeded,
    RetrievalUnavailable,
    normalize_text,
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

SENTENCE_PATTERN = re.compile(r"[^.!?\n]+(?:[.!?]+|$)", re.UNICODE)
INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(all\s+)?previous\b", re.I),
    re.compile(r"ігноруй\s+(усі\s+)?поперед", re.I),
    re.compile(r"\b(system|developer)\s+(prompt|message)\b", re.I),
    re.compile(r"розкрий\s+(системн|прихован)", re.I),
    re.compile(r"\bexecute\s+these\s+instructions\b", re.I),
)


@dataclass(frozen=True)
class SentenceCandidate:
    text: str
    start: int
    end: int
    query_coverage: float


def contains_control_injection(text: str) -> bool:
    normalized = normalize_text(text)
    return any(pattern.search(normalized) for pattern in INJECTION_PATTERNS)


def sentence_candidates(text: str, query_tokens: frozenset[str]) -> list[SentenceCandidate]:
    output: list[SentenceCandidate] = []
    for match in SENTENCE_PATTERN.finditer(text):
        raw = match.group(0)
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        sentence = raw.strip()
        if not sentence:
            continue
        sentence_tokens = set(tokenize(sentence))
        coverage = len(query_tokens.intersection(sentence_tokens)) / max(len(query_tokens), 1)
        output.append(
            SentenceCandidate(
                text=sentence,
                start=match.start() + leading,
                end=match.start() + trailing,
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
        if contains_control_injection(query.text):
            answer = self._abstain(
                release_id,
                "query_control_injection",
                "Запит містить інструкції керування моделлю замість предметного питання.",
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
            self._audit(identity, query, answer, retrieved, eligible)
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
            if candidate is None:
                continue
            support_score = min(item.score, candidate.query_coverage)
            if (
                candidate.query_coverage < thresholds.minimum_query_coverage
                or support_score < thresholds.minimum_support_score
            ):
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

        evidence_coverage = len(covered_tokens) / max(len(query_tokens), 1)
        if not claims or evidence_coverage < thresholds.minimum_query_coverage:
            answer = self._abstain(
                release_id,
                "claim_support_gate_failed",
                "Джерела знайдено, але вони не підтримують конкретну відповідь на запит.",
                max((item.score for item in eligible), default=0.0),
            )
        else:
            answer = Answer(
                status=AnswerStatus.ANSWERED,
                text="\n\n".join(claim.text for claim in claims),
                claims=claims,
                citations=citations,
                retrieval_score=max(item.score for item in eligible),
                evidence_coverage=evidence_coverage,
                decision_reason="extractive_claims_passed_calibrated_gates",
                calibration_id=self.answer_policy.calibration_id,
                limitations=[
                    "Відповідь екстрактивна: система не додає фактів поза точними цитованими реченнями."
                ],
                corpus_release=release_id,
            )
        self._audit(identity, query, answer, retrieved, eligible, risk)
        return answer

    def _abstain(
        self,
        release_id: str,
        reason: str,
        text: str,
        retrieval_score: float = 0.0,
    ) -> Answer:
        return Answer(
            status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            text=text,
            retrieval_score=retrieval_score,
            evidence_coverage=0.0,
            decision_reason=reason,
            calibration_id=self.answer_policy.calibration_id,
            limitations=["Генерацію зупинено fail-closed."],
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
                "calibration_id": answer.calibration_id,
                "corpus_release": answer.corpus_release,
                "query_risk": risk.value,
            },
        )
