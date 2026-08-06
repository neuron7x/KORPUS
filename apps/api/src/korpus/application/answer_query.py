from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from korpus.application.evidence import (
    SupportVerdict,
    assess_control_injection,
    contradiction_reason,
    extractive_support,
    refuting_sentence,
    segment_sentences,
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


@dataclass(frozen=True)
class ScopeBreach:
    """Evidence the retriever returned that the reader was never authorized to see."""

    version_id: str
    kind: str
    detail: str


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
            and item.version.authority.is_normative
        ]


class ExtractiveAnswerService:
    def __init__(
        self,
        repository: Repository,
        retriever: Retriever,
        policy_engine: PolicyEngine,
        answer_policy: AnswerPolicy,
        query_planner: QueryPlanner | None = None,
    ) -> None:
        self.repository = repository
        self.retriever = retriever
        self.policy_engine = policy_engine
        self.answer_policy = answer_policy
        #: Optional by construction. Absent, this service behaves exactly as it did
        #: before one existed — which is what every failure of a present one degrades to.
        self.query_planner = query_planner

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
        # The question is searched first and always. A reformulation widens what was
        # looked for; it cannot replace what was asked, because a planner that quietly
        # substituted its own phrasing could steer a reader away from the passage they
        # came for and nothing downstream would see it happen.
        plan = build_plan(query.text, self.query_planner)
        try:
            retrieved = self._search_plan(identity, plan, corpora, query.as_of)
        except RetrievalDeadlineExceeded:
            answer = self._abstain(
                release_id,
                "retrieval_deadline_exceeded",
                "Пошук не завершився у межах операційного бюджету; відповідь зупинено.",
            )
            self._audit(identity, query, answer, [], [], risk, plan=plan)
            return answer
        except RetrievalUnavailable:
            answer = self._abstain(
                release_id,
                "retrieval_dependency_unavailable",
                "Обов’язковий пошуковий контур недоступний;"
                " відповідь зупинено без слабшого fallback.",
            )
            self._audit(identity, query, answer, [], [], risk, plan=plan)
            return answer

        breaches = self._scope_breaches(identity, corpora, retrieved)
        if breaches:
            answer = self._breach(release_id, breaches)
            self._audit(
                identity, query, answer, retrieved, [], risk, breaches=breaches, plan=plan
            )
            return answer

        eligible = self.answer_policy.eligible(retrieved, risk)
        if not eligible:
            answer = self._abstain(
                release_id,
                "retrieval_gate_failed",
                "У чинному перевіреному корпусі недостатньо доказів для надійної відповіді.",
                max((item.score for item in retrieved), default=0.0),
            )
            self._audit(identity, query, answer, retrieved, eligible, risk, plan=plan)
            return answer

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
            self._audit(identity, query, answer, retrieved, eligible, risk, plan=plan)
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
                identity, query, answer, retrieved, eligible, risk, support=support, plan=plan
            )
            return answer
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
                        "Відповідь екстрактивна: система не додає фактів"
                        " поза точними цитованими реченнями.",
                        "Retrieval score є ranking utility, а не ймовірністю істинності.",
                        *self._source_limitations(citations, outranked, eligible),
                    ],
                    corpus_release=release_id,
                )
        self._audit(identity, query, answer, retrieved, eligible, risk, plan=plan)
        return answer

    def _search_plan(
        self,
        identity: Identity,
        plan: QueryPlan,
        corpora: frozenset[str],
        as_of: date,
    ) -> list[RetrievedEvidence]:
        """Every search in the plan, fused by span, ranked as one set.

        Scores from different queries are comparable because they are produced by the
        same scorer against the same corpus; the highest is kept when a span is found
        twice, which is the score of the phrasing that matched it best. What is not
        done is boosting a span for appearing under several phrasings: that would let
        the number of reformulations a model happened to emit decide relevance.
        """
        best: dict[str, RetrievedEvidence] = {}
        for text in plan.searches:
            for item in self.retriever.search(identity, text, corpora, as_of):
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
        """Seam for the support gate's adversary.

        The gate exists for the case where extraction stops producing byte-for-byte
        extracts. No such extraction exists in the tree, so the case is produced by
        substituting this method — without a seam the gate would again be a branch
        nothing can reach, which is the defect being fixed.
        """

        return sentence_candidates(text, query_tokens)

    def _scope_breaches(
        self,
        identity: Identity,
        corpora: frozenset[str],
        retrieved: list[RetrievedEvidence],
    ) -> list[ScopeBreach]:
        """Re-check, in the application layer, what the retriever claims is in scope.

        `Retriever` is a port. Today the only adapter narrows the query in SQL, but a
        second adapter, a cache returning a neighbouring reader's rows, or a defect in
        the one adapter that exists would widen disclosure with nothing above it
        objecting. The check is deliberately not a filter: silently dropping the row
        would answer from the remainder and leave the defective adapter in service.
        """
        breaches: list[ScopeBreach] = []
        for item in retrieved:
            document = item.document
            version_id = str(item.version.id)
            if document.corpus_id not in corpora:
                breaches.append(
                    ScopeBreach(
                        version_id,
                        "corpus_out_of_scope",
                        f"corpus {document.corpus_id} was not authorized for this query",
                    )
                )
                continue
            decision = self.policy_engine.can_access_document(identity, document)
            if not decision.allowed:
                breaches.append(ScopeBreach(version_id, "reader_not_cleared", decision.reason))
        return breaches

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
        """A quote must occur verbatim in the span it names.

        `make_spans` now slices the page, so this holds by construction — but the
        construction is exactly what failed before: spans were assembled by joining the
        tail of one to the head of the next, and the manufactured sentence left the
        system as a verbatim citation with a matching `quote_hash`. The hash proves the
        quote matches itself, not the document. This is the check that would have
        caught it, and it stays as the second line for whatever changes chunking next.
        """
        span_text = {str(item.span.id): item.span.text for item in eligible}
        return [
            str(citation.span_id)
            for citation in citations
            if citation.quote not in span_text.get(str(citation.span_id), "")
        ]

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
        """Name what the ranking discarded, what repeats, and what has no stated date."""
        limitations: list[str] = []
        # A library copy carries the date it was *seen*, not the date the document took
        # force: `effective_from` is set from the snapshot so the source can never be
        # cited as governing an earlier date, and `publication_date` is left empty
        # because nobody established it. Silence about that difference would let a
        # reader take the lower bound for a publication date, which is the one reading
        # the field cannot support.
        undated = {
            item.version.id for item in used if item.version.publication_date is None
        }
        cited_undated = sum(1 for citation in citations if citation.version_id in undated)
        if cited_undated:
            limitations.append(
                f"{cited_undated} цитат із джерел без встановленої дати публікації:"
                " нижня межа чинності — дата копії в бібліотеці, не дата видання."
            )
        if outranked:
            classes = sorted({item.version.authority.value for item in outranked})
            limitations.append(
                f"Не використано {len(outranked)} джерел нижчого рангу"
                f" ({', '.join(classes)}): ранг джерела не перебивається схожістю."
            )
        per_version: dict[UUID, int] = {}
        for citation in citations:
            per_version[citation.version_id] = per_version.get(citation.version_id, 0) + 1
        repeated = sum(1 for count in per_version.values() if count > 1)
        if repeated:
            limitations.append(
                f"{repeated} версій цитовано більше ніж один раз:"
                " кілька цитат з однієї версії — це одне джерело, а не кілька."
            )
        return limitations

    @staticmethod
    def _confine_to_top_authority(
        eligible: list[RetrievedEvidence],
    ) -> tuple[list[RetrievedEvidence], list[RetrievedEvidence]]:
        """Keep only the strongest authority class present, and say how many were dropped.

        Authority was one term of a convex sum, so an analytical passage that matched
        the query well could sit beside — and contradict — the official order it
        comments on. Two consequences followed: the weaker source was cited as if it
        were equal, and `_find_contradiction` compared it against the stronger one and
        pushed the whole answer to REQUIRES_HUMAN_REVIEW. A lower-ranked source cannot
        overrule a higher-ranked one, so it also cannot veto it.
        """
        if not eligible:
            return [], []
        top = max(AUTHORITY_PRIOR[item.version.authority] for item in eligible)
        confined = [item for item in eligible if AUTHORITY_PRIOR[item.version.authority] == top]
        outranked = [item for item in eligible if AUTHORITY_PRIOR[item.version.authority] < top]
        return confined, outranked

    @staticmethod
    def _find_contradiction(
        claims: list[Claim],
        citations: list[Citation],
        eligible: list[RetrievedEvidence],
    ) -> str | None:
        """Two live versions of one document conflict whatever their text says.

        Textual contradiction detection is lexical and numeric: two versions of the
        same order that disagree only in a date, a annex reference or a signature block
        pass it silently. Which of them governs is not a question the system may answer
        by ranking — the corpus is in a state a human has to resolve.

        The last check reads the *whole* text of every eligible span, not just the
        sentences extraction happened to select. A span whose next sentence reversed
        the one quoted used to answer cleanly (destruction stage B2): the reader
        opening the source saw the reversal, the system that sent them there did not.
        Whether the second sentence is a genuine conflict or an exception carved out of
        the first is not decidable lexically, and it is not the system's decision to
        make — both readings end at the same place, a human reading the passage.

        The scan covers eligible spans rather than only cited ones. An eligible span
        already cleared relevance, currency and the top authority class; a refutation
        sitting in one the extractor did not happen to quote is still the corpus
        disagreeing with itself, and narrowing the scan to citations would let the
        selection step decide which contradictions count.
        """
        versions_by_document: dict[UUID, set[UUID]] = {}
        for citation in citations:
            versions_by_document.setdefault(citation.document_id, set()).add(citation.version_id)
        ordered = sorted(versions_by_document.items(), key=lambda entry: str(entry[0]))
        for document_id, version_ids in ordered:
            if len(version_ids) > 1:
                return f"multiple_current_versions:{document_id}"
        for left_index, left in enumerate(claims):
            for right in claims[left_index + 1 :]:
                reason = contradiction_reason(left.text, right.text)
                if reason is not None:
                    return reason
        for claim in claims:
            for item in eligible:
                refutation = refuting_sentence(claim.text, item.span.text)
                if refutation is not None:
                    _sentence, reason = refutation
                    return f"refuted_by_evidence:{reason}"
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
        *,
        breaches: list[ScopeBreach] | None = None,
        support: SupportVerdict | None = None,
        plan: QueryPlan | None = None,
    ) -> None:
        if support is not None and not support.aligned:
            self.repository.append_audit(
                identity,
                "answer.citation_misalignment",
                "answer",
                str(answer.id),
                {
                    "decision_reason": answer.decision_reason,
                    "unsupported_claims": list(support.unsupported_claim_indexes),
                    "reasons": list(support.reasons[:8]),
                },
            )
        if breaches:
            self.repository.append_audit(
                identity,
                "answer.scope_breach",
                "answer",
                str(answer.id),
                {
                    "decision_reason": answer.decision_reason,
                    "breaches": [
                        {
                            "version_id": breach.version_id,
                            "kind": breach.kind,
                            "detail": breach.detail,
                        }
                        for breach in breaches
                    ],
                    "requested_corpora": query.corpus_ids,
                    "reader_clearance": int(identity.clearance),
                },
            )
        thresholds = risk_adjusted_thresholds(
            risk,
            minimum_score=self.answer_policy.minimum_score,
            minimum_query_coverage=self.answer_policy.minimum_query_coverage,
            minimum_support_score=self.answer_policy.minimum_support_score,
        )
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
                # Both halves of "who asked this": the subject the token carried is the
                # event's actor, and this is the name the person at the keyboard gave.
                # Recorded under `declared` because it is unverified — an investigator
                # must be able to tell an assertion from a proof, and the field name is
                # where that distinction survives being read six months later.
                "declared": (
                    {
                        "given_name": query.declaration.given_name,
                        "family_name": query.declaration.family_name,
                        "specialty": query.declaration.specialty,
                        "verified": False,
                    }
                    if query.declaration is not None
                    else None
                ),
                # What was actually searched for. An answer assembled partly from a
                # machine-suggested phrasing is a different event from one built on the
                # words a soldier typed, and a record that cannot tell them apart cannot
                # answer "why did it show me this" six months from now.
                "query_plan": plan.as_audit_record() if plan is not None else None,
                "retrieved": len(retrieved),
                "eligible": len(eligible),
                "citation_count": len(answer.citations),
                "evidence_coverage": answer.evidence_coverage,
                "query_coverage": answer.query_coverage,
                "retrieval_score_kind": answer.retrieval_score_kind,
                "calibration_id": answer.calibration_id,
                "corpus_release": answer.corpus_release,
                "query_risk": risk.value,
                # Counts cannot answer the question an investigation has. Which edition
                # governed, which passage was quoted, on what date and against which
                # bar were all absent from the record, so "why was this answered and
                # that withheld" was unreconstructable once the answer object was gone.
                # The date is recorded even for abstentions: `as_of` decides which
                # edition is current, and an abstention on the wrong date looks exactly
                # like an abstention on an empty corpus.
                "as_of": query.as_of.isoformat(),
                "thresholds": {
                    "minimum_score": thresholds.minimum_score,
                    "minimum_query_coverage": thresholds.minimum_query_coverage,
                    "minimum_support_score": thresholds.minimum_support_score,
                    "minimum_authority": thresholds.minimum_authority,
                },
                "citations": [
                    {
                        "document_id": str(citation.document_id),
                        "version_id": str(citation.version_id),
                        "span_id": str(citation.span_id),
                        "revision": citation.revision,
                        "quote_hash": citation.quote_hash,
                    }
                    for citation in answer.citations
                ],
            },
        )
