from __future__ import annotations

import re
from dataclasses import dataclass

from korpus.application.ports import Repository, Retriever
from korpus.application.policy import PolicyEngine
from korpus.application.retrieval import tokenize
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

SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
INJECTION_MARKERS = (
    "ignore previous",
    "ігноруй поперед",
    "system prompt",
    "developer message",
    "виконай інструкц",
)


@dataclass(frozen=True)
class AnswerPolicy:
    minimum_score: float
    minimum_query_coverage: float
    max_claims: int = 4

    def eligible(self, evidence: list[RetrievedEvidence]) -> list[RetrievedEvidence]:
        return [
            item
            for item in evidence
            if item.score >= self.minimum_score
            and item.query_coverage >= self.minimum_query_coverage
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
        retrieved = self.retriever.search(identity, query.text, corpora, query.as_of)
        eligible = self.answer_policy.eligible(retrieved)
        release_id = self.repository.corpus_release_id()
        if not eligible:
            answer = Answer(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                text="У чинному перевіреному корпусі недостатньо доказів для надійної відповіді.",
                retrieval_score=max((item.score for item in retrieved), default=0.0),
                evidence_coverage=0.0,
                limitations=["Генерацію зупинено: доказовий поріг не пройдено."],
                corpus_release=release_id,
            )
            self._audit(identity, query, answer, retrieved, eligible)
            return answer

        query_tokens = set(tokenize(query.text))
        claims: list[Claim] = []
        citations: list[Citation] = []
        seen_sentences: set[str] = set()
        seen_spans: set[str] = set()

        for item in eligible:
            sentences = [part.strip() for part in SENTENCE_PATTERN.split(item.span.text) if part.strip()]
            ranked = sorted(
                sentences,
                key=lambda sentence: len(query_tokens.intersection(tokenize(sentence))),
                reverse=True,
            )
            sentence = next((candidate for candidate in ranked if candidate not in seen_sentences), None)
            if sentence is None:
                continue
            # Retrieved content is quoted as data. Instruction-like strings never become control text.
            if any(marker in sentence.casefold() for marker in INJECTION_MARKERS):
                sentence = f"[Непридатний інструктивний фрагмент у джерелі вилучено з відповіді]"
                continue
            overlap = len(query_tokens.intersection(tokenize(sentence))) / max(len(query_tokens), 1)
            if overlap < self.answer_policy.minimum_query_coverage:
                continue
            claims.append(
                Claim(
                    text=sentence,
                    evidence_span_ids=(item.span.id,),
                    support_state=SupportState.EXTRACTIVE,
                    support_score=min(1.0, max(overlap, item.score)),
                )
            )
            seen_sentences.add(sentence)
            if str(item.span.id) not in seen_spans:
                citations.append(
                    Citation(
                        document_id=item.document.id,
                        version_id=item.version.id,
                        span_id=item.span.id,
                        title=item.document.canonical_title,
                        revision=item.version.revision,
                        page=item.span.page,
                        section=item.span.section,
                        quote=item.span.text[:1600],
                        source_uri=item.version.source_uri,
                        source_hash=item.version.source_hash,
                    )
                )
                seen_spans.add(str(item.span.id))
            if len(claims) >= self.answer_policy.max_claims:
                break

        if not claims:
            answer = Answer(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                text="Джерела знайдено, але вони не підтримують конкретну відповідь на запит.",
                retrieval_score=eligible[0].score,
                evidence_coverage=0.0,
                limitations=["Відсутній достатній claim-to-span overlap."],
                corpus_release=release_id,
            )
        else:
            answer = Answer(
                status=AnswerStatus.ANSWERED,
                text="\n\n".join(claim.text for claim in claims),
                claims=claims,
                citations=citations,
                retrieval_score=max(item.score for item in eligible),
                evidence_coverage=1.0,
                limitations=["Відповідь екстрактивна: система не додає фактів поза цитованими фрагментами."],
                corpus_release=release_id,
            )
        self._audit(identity, query, answer, retrieved, eligible)
        return answer

    def _audit(
        self,
        identity: Identity,
        query: QueryRequest,
        answer: Answer,
        retrieved: list[RetrievedEvidence],
        eligible: list[RetrievedEvidence],
    ) -> None:
        self.repository.append_audit(
            identity,
            "answer.completed",
            "answer",
            str(answer.id),
            {
                "status": answer.status.value,
                "query_hash": __import__("hashlib").sha256(query.text.encode()).hexdigest(),
                "requested_corpora": query.corpus_ids,
                "retrieved": len(retrieved),
                "eligible": len(eligible),
                "citation_count": len(answer.citations),
                "corpus_release": answer.corpus_release,
            },
        )
