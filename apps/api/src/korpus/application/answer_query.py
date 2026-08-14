from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import cast

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
from korpus.application.answer_audit import append_answer_audit
from korpus.application.composition import AnswerComposer, Composition, compose_answer
from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    CorpusReadToken,
    CorpusSnapshotReader,
    SnapshotRetriever,
)
from korpus.application.egress import ModelEgressPolicy
from korpus.application.evidence import (
    SupportVerdict,
    assess_control_injection,
    extractive_support,
    verify_claim_support,
)
from korpus.application.policy import PolicyEngine
from korpus.application.ports import Repository, Retriever
from korpus.application.query_plan import QueryPlan, QueryPlanner, build_plan
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
from korpus.application.snapshot_retrieval import SnapshotBoundRetriever
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
        self.repository = repository
        resolved_reader = (
            snapshot_reader
            or getattr(retriever, "snapshot_reader", None)
            or getattr(repository, "corpus_snapshot_reader", None)
        )
        if resolved_reader is None:
            raise ValueError("a corpus snapshot reader is required for answering")
        self.snapshot_reader = cast(CorpusSnapshotReader, resolved_reader)
        # Compatibility at the application boundary is still fail-closed: an ordinary
        # retriever is wrapped with before/after epoch validation. Production supplies
        # CachedRetriever directly, which already consumes the explicit token.
        if hasattr(retriever, "snapshot_reader"):
            self.retriever = cast(SnapshotRetriever, retriever)
        else:
            self.retriever = SnapshotBoundRetriever(
                self.snapshot_reader, cast(Retriever, retriever)
            )
        self.policy_engine = policy_engine
        self.answer_policy = answer_policy
        #: Optional by construction. Absent, this service behaves exactly as it did
        #: before one existed — which is what every failure of a present one degrades to.
        self.query_planner = query_planner
        #: Arranges the retrieved sentences and proposes one opening line. Absent, or
        #: refused, the answer is the extract exactly as it was.
        self.answer_composer = answer_composer
        #: GOV-006. Governs whether the material a composer would send may leave the
        #: deployment for its classification. Absent, no ceiling is applied — the seam a
        #: test uses to build the service without a corpus posture, and the pre-existing
        #: behaviour of every service that never had one. The composition root always
        #: supplies it.
        self.egress_policy = egress_policy

    def execute(self, identity: Identity, query: QueryRequest) -> Answer:
        corpora = self.policy_engine.resolve_corpora(identity, query.corpus_ids)
        try:
            token = self.snapshot_reader.capture(identity, corpora, query.as_of)
        except CorpusConsistencyError as exc:
            answer = self._abstain(
                "snapshot-unavailable",
                "corpus_snapshot_unavailable",
                "Стан перевіреного корпусу неможливо зафіксувати узгоджено; відповідь зупинено.",
                limitations=[f"Snapshot consistency: {type(exc).__name__}."],
            )
            self._audit(
                identity,
                query,
                answer,
                [],
                [],
                classify_query_risk(query.text),
                token=None,
            )
            return answer
        release_id = token.release_id

        injection = assess_control_injection(query.text)
        if injection.blocked:
            answer = self._abstain(
                release_id,
                "query_control_injection",
                "Запит містить інструкції керування системою замість предметного питання.",
                limitations=[f"Injection signals: {', '.join(injection.reasons)}"],
            )
            return self._finalize(
                identity,
                query,
                answer,
                [],
                [],
                classify_query_risk(query.text),
                corpora,
                token,
            )

        risk = classify_query_risk(query.text)
        # The question is searched first and always. A reformulation widens what was
        # looked for; it cannot replace what was asked, because a planner that quietly
        # substituted its own phrasing could steer a reader away from the passage they
        # came for and nothing downstream would see it happen.
        plan = build_plan(query.text, self.query_planner)
        try:
            retrieved = self._search_plan(identity, plan, corpora, query.as_of, token)
        except CorpusConsistencyError:
            answer = self._abstain(
                release_id,
                "corpus_snapshot_changed",
                "Корпус змінився під час пошуку; результат відкинуто без переходу до нового стану.",
            )
            self._audit(identity, query, answer, [], [], risk, plan=plan, token=token)
            return answer
        except RetrievalDeadlineExceeded:
            answer = self._abstain(
                release_id,
                "retrieval_deadline_exceeded",
                "Пошук не завершився у межах операційного бюджету; відповідь зупинено.",
            )
            return self._finalize(
                identity, query, answer, [], [], risk, corpora, token, plan=plan
            )
        except RetrievalUnavailable:
            answer = self._abstain(
                release_id,
                "retrieval_dependency_unavailable",
                "Обов’язковий пошуковий контур недоступний;"
                " відповідь зупинено без слабшого fallback.",
            )
            return self._finalize(
                identity, query, answer, [], [], risk, corpora, token, plan=plan
            )

        breaches = self._scope_breaches(identity, corpora, retrieved)
        if breaches:
            answer = self._breach(release_id, breaches)
            return self._finalize(
                identity,
                query,
                answer,
                retrieved,
                [],
                risk,
                corpora,
                token,
                breaches=breaches,
                plan=plan,
            )

        eligible = self.answer_policy.eligible(retrieved, risk)
        if not eligible:
            answer = self._abstain(
                release_id,
                "retrieval_gate_failed",
                "У чинному перевіреному корпусі недостатньо доказів для надійної відповіді.",
                max((item.score for item in retrieved), default=0.0),
            )
            return self._finalize(
                identity, query, answer, retrieved, eligible, risk, corpora, token, plan=plan
            )

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
            return self._finalize(
                identity, query, answer, retrieved, eligible, risk, corpora, token, plan=plan
            )

        query_coverage = len(covered_tokens) / max(len(query_tokens), 1)
        support = verify_claim_support(
            [(index, claim.evidence_span_ids) for index, claim in enumerate(claims)],
            [citation.span_id for citation in citations],
        )
        evidence_coverage = support.coverage
        if claims and not support.aligned:
            answer = self._misaligned(release_id, support)
            return self._finalize(
                identity,
                query,
                answer,
                retrieved,
                eligible,
                risk,
                corpora,
                token,
                support=support,
                plan=plan,
            )
        # Before every branch, not inside one: three of them reach the same audit call,
        # and initialising it in the branch that uses it surfaced as an UnboundLocalError
        # on the other two rather than as a missing field.
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
                # The model may arrange what was found and open with one line. It may
                # not add a fact: `compose_answer` refuses an opening that states a
                # number, introduces a negation, or uses a content word the cited spans
                # do not contain, and a refusal leaves the extract untouched.
                #
                # GOV-006: before that, whether the material may leave at all. If the
                # sentences outrank the egress ceiling, the composer is not called with
                # them — sending them to a model outside the deployment would exfiltrate
                # restricted spans, whatever the composer returned. The extract stands and
                # the reason travels into the audit chain.
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
        return self._finalize(
            identity,
            query,
            answer,
            retrieved,
            eligible,
            risk,
            corpora,
            token,
            plan=plan,
            composition=composition_reason,
        )

    def _finalize(
        self,
        identity: Identity,
        query: QueryRequest,
        answer: Answer,
        retrieved: list[RetrievedEvidence],
        eligible: list[RetrievedEvidence],
        risk: QueryRisk,
        corpora: frozenset[str],
        token: CorpusReadToken,
        *,
        breaches: list[ScopeBreach] | None = None,
        support: SupportVerdict | None = None,
        plan: QueryPlan | None = None,
        composition: str | None = None,
    ) -> Answer:
        """Linearization point for an answer: validate the token before audit/return."""
        try:
            self.snapshot_reader.validate(identity, corpora, query.as_of, token)
        except CorpusConsistencyError:
            answer = self._abstain(
                token.release_id,
                "corpus_snapshot_changed",
                "Корпус змінився до завершення відповіді; зібраний результат відкинуто.",
            )
            retrieved = []
            eligible = []
            breaches = None
            support = None
            composition = "discarded: corpus snapshot changed"
        self._audit(
            identity,
            query,
            answer,
            retrieved,
            eligible,
            risk,
            breaches=breaches,
            support=support,
            plan=plan,
            composition=composition,
            token=token,
        )
        return answer

    def _compose(
        self, query: QueryRequest, claims: list[Claim], eligible: list[RetrievedEvidence]
    ) -> tuple[Composition | None, str]:
        """The arranged answer and why — or the extract and the reason it was withheld.

        The egress ceiling is asked before the composer, not inside it: the composer never
        sees material it may not send, rather than being trusted to refuse it. Its own
        `compose_answer` still guards what a permitted composer may *say*.
        """
        if not self._composition_egress_permitted(claims, eligible):
            return None, "egress_tier_exceeded"
        return compose_answer(
            query.text, [claim.text for claim in claims], self.answer_composer
        )

    def _composition_egress_permitted(
        self, claims: list[Claim], eligible: list[RetrievedEvidence]
    ) -> bool:
        """Whether the sentences a composer would send may leave the deployment.

        The material sent is the claim text, so the tier that matters is the highest
        classification among the documents whose spans actually back those claims — not
        every eligible document, which would refuse composition for a public answer merely
        because a restricted document ranked alongside it and produced no surviving claim.
        A span with no known tier is treated as the most restrictive, not the least: the
        one case where guessing is a leak.
        """
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

    def _search_plan(
        self,
        identity: Identity,
        plan: QueryPlan,
        corpora: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
    ) -> list[RetrievedEvidence]:
        """Every search in the plan, fused by span, ranked as one set.

        Every reformulation receives the same token. Scores from different queries are
        comparable because they are produced by the same scorer against the same corpus;
        the highest is kept when a span is found twice. Appearing under several phrasings
        does not boost a span.
        """
        best: dict[str, RetrievedEvidence] = {}
        for text in plan.searches:
            for item in self.retriever.search(identity, text, corpora, as_of, token):
                key = str(item.span.id)
                previous = best.get(key)
                if previous is None or item.score > previous.score:
                    best[key] = item
        return sorted(
            best.values(),
            key=lambda item: (-item.score, -item.query_coverage, item.span.ordinal),
        )

    def _extract(
        self,
        eligible: list[RetrievedEvidence],
        query_tokens: frozenset[str],
        thresholds: RiskThresholds,
    ) -> tuple[list[Claim], list[Citation], set[str]]:
        """Build claim/citation pairs from eligible evidence.

        Kept separate from `execute` so that the alignment check downstream has an
        adversary: a substituted extraction can emit a claim that references a span the
        answer does not carry, which is exactly the condition `verify_claim_support`
        exists to catch and which the coupled loop could never produce.
        """
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
            # Measured rather than asserted. It used to be the constant 1.0 against a
            # threshold clamped to at most 1.0, so the branch below was unreachable in
            # every configuration and `SupportState.UNSUPPORTED` was produced nowhere.
            # For a byte-for-byte extract the value is 1.0 by construction; it moves
            # only if extraction stops being exact, which is the case the gate exists
            # for. Relevance remains a separate query-coverage gate.
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
        """A claim that points outside the answer's own citations carries no evidence.

        The previous shape of this computation could produce `evidence_coverage > 1`
        and raise `ValidationError` inside the response model — a 500 where the value
        function requires an abstention. Coverage is reported as 0.0 here because a
        partially referenced answer earns no partial credit.
        """
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

    def _audit(
        self,
        identity: Identity,
        query: QueryRequest,
        answer: Answer,
        retrieved: list[RetrievedEvidence],
        eligible: list[RetrievedEvidence],
        risk: QueryRisk = QueryRisk.STANDARD,
        *,
        breaches: list[ScopeBreach] | None = None,
        support: SupportVerdict | None = None,
        plan: QueryPlan | None = None,
        composition: str | None = None,
        token: CorpusReadToken | None = None,
    ) -> None:
        append_answer_audit(
            self.repository,
            identity,
            query,
            answer,
            retrieved,
            eligible,
            risk,
            minimum_score=self.answer_policy.minimum_score,
            minimum_query_coverage=self.answer_policy.minimum_query_coverage,
            minimum_support_score=self.answer_policy.minimum_support_score,
            breaches=breaches,
            support=support,
            plan=plan,
            composition=composition,
            token=token,
        )
