from __future__ import annotations

import hashlib
from dataclasses import dataclass
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
from korpus.application.answer_retrieval_gate import apply_retrieval_gate
from korpus.application.composition import AnswerComposer, Composition, compose_answer
from korpus.application.egress import ModelEgressPolicy
from korpus.application.answer_adjudication import AxisVerdict, adjudicate, presentation
from korpus.application.evidence import (
    SupportVerdict,
    assess_control_injection,
    extractive_support,
    starts_mid_sentence,
    verify_claim_support,
)
from korpus.application.evidence_admission import eligible_evidence
from korpus.application.pec_retrieval import adaptive_retrieval
from korpus.application.policy import PolicyEngine
from korpus.application.ports import Repository, Retriever
from korpus.application.predictive_evidence_control import (
    ControllerTrace,
    PredictiveEvidenceController,
)
from korpus.application.query_plan import QueryPlan, QueryPlanner
from korpus.application.retrieval import (
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
        return eligible_evidence(evidence, thresholds)


#: Порядок присуду: підтверджене попереду дотичного, дотичне попереду спірного.
_PRESENTATION_RANK = {"supported": 0, "tangential": 1, "contested": 2}


def _dissent(verdicts: tuple[AxisVerdict, ...]) -> str:
    """Найсильніше заперечення словами тієї осі, що його висловила.

    Порожній рядок означає «жодна вісь не заперечила», а не «все перевірено»: осі,
    які утримались, лишаються утриманими.
    """
    for wanted in ("DOES_NOT_SUPPORT", "CANNOT_ADJUDICATE"):
        for item in verdicts:
            if item.verdict == wanted:
                return item.reason
    return ""


class ExtractiveAnswerService:
    def __init__(
        self,
        repository: Repository,
        retriever: Retriever,
        policy_engine: PolicyEngine,
        answer_policy: AnswerPolicy,
        query_planner: QueryPlanner | None = None,
        answer_composer: AnswerComposer | None = None,
        egress_policy: ModelEgressPolicy | None = None,
        predictive_controller: PredictiveEvidenceController | None = None,
    ) -> None:
        self.repository = repository
        self.retriever = retriever
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
        self.predictive_controller = predictive_controller

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
        retrieval_thresholds = risk_adjusted_thresholds(
            risk,
            minimum_score=self.answer_policy.minimum_score,
            minimum_query_coverage=self.answer_policy.minimum_query_coverage,
            minimum_support_score=self.answer_policy.minimum_support_score,
        )
        pec_trace: ControllerTrace | None = None
        plan = QueryPlan(asked=query.text)
        try:
            retrieval_outcome = adaptive_retrieval(
                identity=identity,
                query_text=query.text,
                corpora=corpora,
                as_of=query.as_of,
                risk=risk,
                admission_thresholds=retrieval_thresholds,
                retriever=self.retriever,
                planner=self.query_planner,
                controller=self.predictive_controller,
                answer_calibration_id=self.answer_policy.calibration_id,
                corpus_release_id=release_id,
                eligible_count=lambda items: len(self.answer_policy.eligible(items, risk)),
            )
            retrieved = retrieval_outcome.retrieved
            plan = retrieval_outcome.plan
            pec_trace = retrieval_outcome.trace
        except RetrievalDeadlineExceeded:
            answer = self._abstain(
                release_id,
                "retrieval_deadline_exceeded",
                "Пошук не завершився у межах операційного бюджету; відповідь зупинено.",
            )
            self._audit(identity, query, answer, [], [], risk, plan=plan, pec_trace=pec_trace)
            return answer
        except RetrievalUnavailable:
            answer = self._abstain(
                release_id,
                "retrieval_dependency_unavailable",
                "Обов’язковий пошуковий контур недоступний;"
                " відповідь зупинено без слабшого fallback.",
            )
            self._audit(identity, query, answer, [], [], risk, plan=plan, pec_trace=pec_trace)
            return answer

        gated, eligible = apply_retrieval_gate(
            self,
            identity=identity,
            query=query,
            release_id=release_id,
            corpora=corpora,
            retrieved=retrieved,
            risk=risk,
            plan=plan,
            pec_trace=pec_trace,
            early_abstain=retrieval_outcome.early_abstain,
        )
        if gated is not None:
            return cast(Answer, gated)
        if eligible is None:
            raise RuntimeError("retrieval gate returned neither a verdict nor eligible evidence")
        thresholds = retrieval_thresholds
        eligible, outranked = self._confine_to_top_authority(eligible)
        query_tokens = frozenset(tokenize(query.text))
        claims, citations, covered_tokens = self._extract(
            eligible, query_tokens, thresholds, query.text
        )

        unsourced = self._unsourced_quotes(eligible, citations)
        if unsourced:
            answer = self._unsourced_answer(release_id, unsourced)
            self._audit(
                identity, query, answer, retrieved, eligible, risk, plan=plan, pec_trace=pec_trace
            )
            return answer

        query_coverage = len(covered_tokens) / max(len(query_tokens), 1)
        support = verify_claim_support(
            [(index, claim.evidence_span_ids) for index, claim in enumerate(claims)],
            [citation.span_id for citation in citations],
        )
        evidence_coverage = support.coverage
        if claims and not support.aligned:
            answer = self._misaligned(release_id, support)
            self._audit(
                identity,
                query,
                answer,
                retrieved,
                eligible,
                risk,
                support=support,
                plan=plan,
                pec_trace=pec_trace,
            )
            return answer
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
            blocked = self._blocked_answer(
                claims, citations, eligible, evidence_coverage, query_coverage, release_id
            )
            if blocked is not None:
                answer = blocked
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
        self._audit(
            identity,
            query,
            answer,
            retrieved,
            eligible,
            risk,
            plan=plan,
            composition=composition_reason,
            pec_trace=pec_trace,
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
        return compose_answer(query.text, [claim.text for claim in claims], self.answer_composer)

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

    def _blocked_answer(
        self,
        claims: list[Claim],
        citations: list[Citation],
        eligible: list[RetrievedEvidence],
        evidence_coverage: float,
        query_coverage: float,
        release_id: str,
    ) -> Answer | None:
        """Причина, з якої автоматична відповідь не виходить, або None.

        Дві причини, і обидві ведуть до людини, а не до мовчання: показана підстава
        не витримала жодної осі, або затверджені джерела суперечать одне одному.
        Зібрані в одному місці, бо `execute` уже несе стільки гілок, скільки стеля
        складності дозволяє: кожна нова причина мусить приходити СЮДИ, а не туди.

        Порядок навмисний. Спірність — властивість того, що система збиралася
        показати; суперечність — властивість корпусу. Перше вирішується без читання
        другого, і повідомлення про спірність точніше для читача.
        """
        if citations and all(citation.presentation == "contested" for citation in citations):
            return self._contested_answer(
                claims,
                citations,
                max(item.score for item in eligible),
                evidence_coverage,
                query_coverage,
                release_id,
            )
        contradiction = self._find_contradiction(claims, citations, eligible)
        if contradiction is None:
            return None
        return Answer(
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

    def _contested_answer(
        self,
        claims: list[Claim],
        citations: list[Citation],
        retrieval_score: float,
        evidence_coverage: float,
        query_coverage: float,
        release_id: str,
    ) -> Answer:
        """Показана підстава не витримала жодної з осей — це справа для людини.

        Не `answered` із позначкою, якої читач може не помітити, і не «підстав немає»:
        уривки знайдено, вони просто не витримали перевірки. Причини кожної осі йдуть
        у `limitations`, щоб людина побачила, ЩО саме заперечили, а не лише що спинили.
        """
        return Answer(
            status=AnswerStatus.REQUIRES_HUMAN_REVIEW,
            text=(
                "Знайдені уривки не витримали перевірки незалежними осями:"
                " автоматичну відповідь зупинено."
            ),
            claims=claims,
            citations=citations,
            retrieval_score=retrieval_score,
            evidence_coverage=evidence_coverage,
            query_coverage=query_coverage,
            decision_reason="all_citations_contested_by_an_independent_axis",
            calibration_id=self.answer_policy.calibration_id,
            limitations=[
                citation.adjudication_reason
                for citation in citations
                if citation.adjudication_reason
            ][:4],
            corpus_release=release_id,
        )

    def _extract(
        self,
        eligible: list[RetrievedEvidence],
        query_tokens: frozenset[str],
        thresholds: RiskThresholds,
        question: str = "",
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
            # Threshold first, then order. Filtering by the same bar the chosen candidate
            # had to clear leaves the admission decision exactly as it was — the best
            # candidate is the highest-covering one, so if it fails, all of them do —
            # and lets the ordering below choose among passages that are already allowed.
            passing = [
                candidate
                for candidate in self._candidates(item.span.text, query_tokens)
                if candidate.query_coverage >= thresholds.minimum_query_coverage
            ]
            # A whole sentence outranks a headless one even when the fragment mentions
            # more of the question. Query coverage measures overlap with the question;
            # it says nothing about whether the passage still carries its own subject.
            # Судять чотири осі, і порядок серед допущених кандидатів визначає їхній
            # присуд, а не саме лише покриття питання. Спірне речення програє дотичному,
            # дотичне — підтвердженому: вісь, яка відхилила, побачила те, куди інші не
            # дивляться, і її голос важить більше за згоду решти.
            candidates = sorted(
                passing,
                key=lambda candidate: (
                    _PRESENTATION_RANK[
                        presentation(
                            adjudicate(
                                question,
                                candidate.text,
                                candidate.query_coverage,
                                thresholds.minimum_query_coverage,
                            )
                        )
                    ],
                    starts_mid_sentence(candidate.text),
                    -candidate.query_coverage,
                    candidate.start,
                ),
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
            axis_verdicts = adjudicate(
                question,
                candidate.text,
                candidate.query_coverage,
                thresholds.minimum_query_coverage,
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
                    quote_starts_mid_sentence=starts_mid_sentence(candidate.text),
                    presentation=presentation(axis_verdicts),
                    adjudication_reason=_dissent(axis_verdicts),
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
        pec_trace: ControllerTrace | None = None,
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
            pec_trace=pec_trace.as_audit_record() if pec_trace is not None else None,
        )
