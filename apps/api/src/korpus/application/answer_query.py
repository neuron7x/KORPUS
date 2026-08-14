from __future__ import annotations

import hashlib
from dataclasses import dataclass

from korpus.application.answer_analysis import (
    ScopeBreach,
    SentenceCandidate,
    confine_to_top_authority,
    contains_control_injection,
    find_contradiction,
    scope_breaches,
    sentence_candidates,
    source_limitations,
    unsourced_quotes,
)
from korpus.application.answer_snapshot import SnapshotAnswerRuntime, SnapshotAuditPolicy
from korpus.application.composition import AnswerComposer, Composition, compose_answer
from korpus.application.corpus_snapshot import CorpusSnapshotReader, SnapshotRetriever
from korpus.application.egress import ModelEgressPolicy
from korpus.application.evidence import (
    SupportVerdict,
    assess_control_injection,
    extractive_support,
    verify_claim_support,
)
from korpus.application.policy import PolicyEngine
from korpus.application.ports import Repository, Retriever
from korpus.application.query_plan import QueryPlanner, build_plan
from korpus.application.retrieval import (
    AUTHORITY_PRIOR,
    RetrievalDeadlineExceeded,
    RetrievalUnavailable,
    tokenize,
)
from korpus.application.risk import (
    QueryRisk,
    RiskThresholds,
    classify_query_risk,
    risk_adjusted_thresholds,
)
from korpus.domain.models import (
    AccessTier,
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
            and item.version.authority.is_normative
        ]


class ExtractiveAnswerService:
    def __init__(
        self,
        repository: Repository,
        retriever: SnapshotRetriever | Retriever,
        policy_engine: PolicyEngine,
        answer_policy: AnswerPolicy,
        query_planner: QueryPlanner | None = None,
        answer_composer: AnswerComposer | None = None,
        egress_policy: ModelEgressPolicy | None = None,
        snapshot_reader: CorpusSnapshotReader | None = None,
    ) -> None:
        self.snapshot_runtime = SnapshotAnswerRuntime(
            repository,
            retriever,
            SnapshotAuditPolicy(
                minimum_score=answer_policy.minimum_score,
                minimum_query_coverage=answer_policy.minimum_query_coverage,
                minimum_support_score=answer_policy.minimum_support_score,
                calibration_id=answer_policy.calibration_id,
            ),
            snapshot_reader,
        )
        self.policy_engine = policy_engine
        self.answer_policy = answer_policy
        self.query_planner = query_planner
        self.answer_composer = answer_composer
        self.egress_policy = egress_policy

    def execute(self, identity: Identity, query: QueryRequest) -> Answer:
        corpora = self.policy_engine.resolve_corpora(identity, query.corpus_ids)
        started = self.snapshot_runtime.begin(identity, query, corpora)
        if isinstance(started, Answer):
            return started
        session = started
        release_id = session.release_id

        injection = assess_control_injection(query.text)
        if injection.blocked:
            answer = self._abstain(
                release_id,
                "query_control_injection",
                "Запит містить інструкції керування системою замість предметного питання.",
                limitations=[f"Injection signals: {', '.join(injection.reasons)}"],
            )
            return session.finish(answer, [], [], classify_query_risk(query.text))

        risk = classify_query_risk(query.text)
        plan = build_plan(query.text, self.query_planner)
        try:
            search_result = session.search_plan(plan, risk)
            if isinstance(search_result, Answer):
                return search_result
            retrieved = search_result
        except RetrievalDeadlineExceeded:
            answer = self._abstain(
                release_id,
                "retrieval_deadline_exceeded",
                "Пошук не завершився у межах операційного бюджету; відповідь зупинено.",
            )
            return session.finish(answer, [], [], risk, plan=plan)
        except RetrievalUnavailable:
            answer = self._abstain(
                release_id,
                "retrieval_dependency_unavailable",
                "Обов’язковий пошуковий контур недоступний;"
                " відповідь зупинено без слабшого fallback.",
            )
            return session.finish(answer, [], [], risk, plan=plan)

        breaches = self._scope_breaches(identity, corpora, retrieved)
        if breaches:
            answer = self._breach(release_id, breaches)
            return session.finish(answer, retrieved, [], risk, breaches=breaches, plan=plan)

        eligible = self.answer_policy.eligible(retrieved, risk)
        if not eligible:
            answer = self._abstain(
                release_id,
                "retrieval_gate_failed",
                "У чинному перевіреному корпусі недостатньо доказів для надійної відповіді.",
                max((item.score for item in retrieved), default=0.0),
            )
            return session.finish(answer, retrieved, eligible, risk, plan=plan)

        thresholds = risk_adjusted_thresholds(
            risk,
            minimum_score=self.answer_policy.minimum_score,
            minimum_query_coverage=self.answer_policy.minimum_query_coverage,
            minimum_support_score=self.answer_policy.minimum_support_score,
        )
        eligible, outranked = self._confine_to_top_authority(eligible)
        query_tokens = frozenset(tokenize(query.text))
        claims, citations, covered_tokens = self._extract(eligible, query_tokens, thresholds)

        unsourced = self._unsourced_quotes(eligible, citations)
        if unsourced:
            answer = self._unsourced_answer(release_id, unsourced)
            return session.finish(answer, retrieved, eligible, risk, plan=plan)

        query_coverage = len(covered_tokens) / max(len(query_tokens), 1)
        support = verify_claim_support(
            [(index, claim.evidence_span_ids) for index, claim in enumerate(claims)],
            [citation.span_id for citation in citations],
        )
        evidence_coverage = support.coverage
        if claims and not support.aligned:
            answer = self._misaligned(release_id, support)
            return session.finish(
                answer, retrieved, eligible, risk, support=support, plan=plan
            )

        composition_reason = "not attempted"
        if not claims or query_coverage < thresholds.minimum_query_coverage:
            answer = self._abstain(
                release_id,
                "claim_support_gate_failed",
                "Джерела знайдено, але вони не підтримують конкретну відповідь на запит.",
                max((item.score for item in eligible), default=0.0),
                query_coverage=query_coverage,
            )
        else:
            contradiction = self._find_contradiction(claims, citations, eligible)
            if contradiction is not None:
                answer = Answer(
                    status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
                    text=(
                        "Затверджені джерела містять взаємно несумісні твердження;"
                        " автоматичну відповідь зупинено."
                    ),
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
                composition, composition_reason = self._compose(query, claims, eligible)
                body = (
                    "\n\n".join(composition.sentences)
                    if composition is not None
                    else "\n\n".join(claim.text for claim in claims)
                )
                answer = Answer(
                    status=AnswerStatus.ANSWERED,
                    text=body,
                    opening=composition.opening if composition is not None else "",
                    claims=claims,
                    citations=citations,
                    retrieval_score=max(item.score for item in eligible),
                    evidence_coverage=evidence_coverage,
                    query_coverage=query_coverage,
                    decision_reason="extractive_claims_passed_calibrated_gates",
                    calibration_id=self.answer_policy.calibration_id,
                    limitations=[
                        "Відповідь екстрактивна: система не додає фактів"
                        " поза точними цитованими реченнями.",
                        "Retrieval score є ranking utility, а не ймовірністю істинності.",
                        *self._source_limitations(citations, outranked, eligible),
                        *(
                            [
                                "Перший рядок написала система з наведених цитат: без "
                                "цифр, без заперечень, лише словами, що є в цитатах."
                            ]
                            if composition is not None
                            else []
                        ),
                    ],
                    corpus_release=release_id,
                )
        return session.finish(
            answer,
            retrieved,
            eligible,
            risk,
            plan=plan,
            composition=composition_reason,
        )

    def _compose(
        self, query: QueryRequest, claims: list[Claim], eligible: list[RetrievedEvidence]
    ) -> tuple[Composition | None, str]:
        if not self._composition_egress_permitted(claims, eligible):
            return None, "egress_tier_exceeded"
        return compose_answer(
            query.text, [claim.text for claim in claims], self.answer_composer
        )

    def _composition_egress_permitted(
        self, claims: list[Claim], eligible: list[RetrievedEvidence]
    ) -> bool:
        if self.egress_policy is None:
            return True
        tier_by_span = {str(item.span.id): item.document.access_tier for item in eligible}
        material_tier = max(
            (
                tier_by_span.get(str(span_id), AccessTier.RESTRICTED)
                for claim in claims
                for span_id in claim.evidence_span_ids
            ),
            default=AccessTier.PUBLIC,
        )
        return self.egress_policy.permits_material(material_tier)

    def _extract(
        self,
        eligible: list[RetrievedEvidence],
        query_tokens: frozenset[str],
        thresholds: RiskThresholds,
    ) -> tuple[list[Claim], list[Citation], set[str]]:
        claims: list[Claim] = []
        citations: list[Citation] = []
        seen_sentences: set[str] = set()
        covered_tokens: set[str] = set()

        for item in eligible:
            candidates = sorted(
                self._candidates(item.span.text, query_tokens),
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
            support_score = extractive_support(candidate.text, item.span.text)
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
                    span_hash=item.span.text_hash,
                    source_uri=item.version.source_uri,
                    source_hash=item.version.source_hash,
                )
            )
            seen_sentences.add(candidate.text)
            covered_tokens.update(set(tokenize(candidate.text)).intersection(query_tokens))
            if len(claims) >= self.answer_policy.max_claims:
                break
        return claims, citations, covered_tokens

    @staticmethod
    def _candidates(text: str, query_tokens: frozenset[str]) -> list[SentenceCandidate]:
        return sentence_candidates(text, query_tokens)

    def _scope_breaches(
        self,
        identity: Identity,
        corpora: frozenset[str],
        retrieved: list[RetrievedEvidence],
    ) -> list[ScopeBreach]:
        return scope_breaches(identity, corpora, retrieved, self.policy_engine)

    def _breach(self, release_id: str, breaches: list[ScopeBreach]) -> Answer:
        kinds = sorted({breach.kind for breach in breaches})
        return Answer(
            status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
            text=(
                "Пошуковий контур повернув матеріал поза дозволеною областю читача;"
                " відповідь зупинено до перевірки людиною."
            ),
            retrieval_score=0.0,
            evidence_coverage=0.0,
            query_coverage=0.0,
            decision_reason="retriever_scope_breach",
            calibration_id=self.answer_policy.calibration_id,
            limitations=[
                "Це не брак доказів, а порушення цілісності доступу в шарі пошуку.",
                f"Breach kinds: {', '.join(kinds)}.",
                f"Affected versions: {len(breaches)}.",
            ],
            corpus_release=release_id,
        )

    @staticmethod
    def _unsourced_quotes(
        eligible: list[RetrievedEvidence], citations: list[Citation]
    ) -> list[str]:
        return unsourced_quotes(eligible, citations)

    def _unsourced_answer(self, release_id: str, span_ids: list[str]) -> Answer:
        return Answer(
            status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
            text=(
                "Цитата не знайдена дослівно у фрагменті, на який посилається;"
                " відповідь зупинено до перевірки людиною."
            ),
            retrieval_score=0.0,
            evidence_coverage=0.0,
            query_coverage=0.0,
            decision_reason="citation_not_present_in_source",
            calibration_id=self.answer_policy.calibration_id,
            limitations=[
                "Хеш цитати доводить збіг цитати із самою собою, не з документом.",
                f"Affected spans: {len(span_ids)}.",
            ],
            corpus_release=release_id,
        )

    def _misaligned(self, release_id: str, support: SupportVerdict) -> Answer:
        return Answer(
            status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
            text=(
                "Твердження посилаються на докази поза набором цитат цієї відповіді;"
                " відповідь зупинено до перевірки людиною."
            ),
            retrieval_score=0.0,
            evidence_coverage=0.0,
            query_coverage=0.0,
            decision_reason="citation_evidence_misalignment",
            calibration_id=self.answer_policy.calibration_id,
            limitations=[
                "Відповідь не містить тверджень: жодне з них не доведене власними цитатами.",
                *support.reasons[:8],
            ],
            corpus_release=release_id,
        )

    @staticmethod
    def _source_limitations(
        citations: list[Citation],
        outranked: list[RetrievedEvidence],
        used: list[RetrievedEvidence],
    ) -> list[str]:
        return source_limitations(citations, outranked, used)

    @staticmethod
    def _confine_to_top_authority(
        eligible: list[RetrievedEvidence],
    ) -> tuple[list[RetrievedEvidence], list[RetrievedEvidence]]:
        return confine_to_top_authority(eligible)

    @staticmethod
    def _find_contradiction(
        claims: list[Claim],
        citations: list[Citation],
        eligible: list[RetrievedEvidence],
    ) -> str | None:
        return find_contradiction(claims, citations, eligible)

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
