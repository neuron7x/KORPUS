"""Temporal linearization boundary for one answer execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from korpus.application.answer_analysis import ScopeBreach
from korpus.application.answer_audit import append_answer_audit
from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    CorpusReadToken,
    CorpusSnapshotReader,
    SnapshotRetriever,
)
from korpus.application.evidence import SupportVerdict
from korpus.application.ports import Repository, Retriever
from korpus.application.query_plan import QueryPlan
from korpus.application.risk import QueryRisk, classify_query_risk
from korpus.application.snapshot_retrieval import SnapshotBoundRetriever
from korpus.domain.models import Answer, AnswerStatus, Identity, QueryRequest, RetrievedEvidence


@dataclass(frozen=True, slots=True)
class SnapshotAuditPolicy:
    minimum_score: float
    minimum_query_coverage: float
    minimum_support_score: float
    calibration_id: str


class SnapshotAnswerAbort(RuntimeError):
    """A consistency path already produced and audited a fail-closed answer."""

    def __init__(self, answer: Answer) -> None:
        super().__init__(answer.decision_reason)
        self.answer = answer


def _resolve_snapshot_reader(
    repository: Repository,
    retriever: SnapshotRetriever | Retriever,
    explicit: CorpusSnapshotReader | None,
) -> CorpusSnapshotReader:
    candidates = [
        candidate
        for candidate in (
            explicit,
            getattr(retriever, "snapshot_reader", None),
            getattr(repository, "corpus_snapshot_reader", None),
        )
        if candidate is not None
    ]
    if not candidates:
        raise ValueError("a corpus snapshot reader is required for answering")
    reader = candidates[0]
    if any(candidate is not reader for candidate in candidates[1:]):
        raise ValueError("answer retrieval must share one corpus snapshot reader")
    return cast(CorpusSnapshotReader, reader)


class SnapshotAnswerRuntime:
    """Resolve the single snapshot authority used by every answer read and audit."""

    def __init__(
        self,
        repository: Repository,
        retriever: SnapshotRetriever | Retriever,
        audit_policy: SnapshotAuditPolicy,
        snapshot_reader: CorpusSnapshotReader | None = None,
    ) -> None:
        self.repository = repository
        self.snapshot_reader = _resolve_snapshot_reader(repository, retriever, snapshot_reader)
        self.audit_policy = audit_policy
        if hasattr(retriever, "snapshot_reader"):
            self.retriever = cast(SnapshotRetriever, retriever)
        else:
            self.retriever = SnapshotBoundRetriever(
                self.snapshot_reader, cast(Retriever, retriever)
            )

    def begin(
        self,
        identity: Identity,
        query: QueryRequest,
        corpora: frozenset[str],
    ) -> SnapshotAnswerSession:
        try:
            token = self.snapshot_reader.capture(identity, corpora, query.as_of)
        except CorpusConsistencyError as exc:
            answer = self.abstain(
                "snapshot-unavailable",
                "corpus_snapshot_unavailable",
                "Стан перевіреного корпусу неможливо зафіксувати узгоджено; відповідь зупинено.",
                limitations=[f"Snapshot consistency: {type(exc).__name__}."],
            )
            self.audit(
                identity,
                query,
                answer,
                [],
                [],
                classify_query_risk(query.text),
                token=None,
            )
            raise SnapshotAnswerAbort(answer) from exc
        return SnapshotAnswerSession(self, identity, query, corpora, token)

    def abstain(
        self,
        release_id: str,
        reason: str,
        text: str,
        *,
        limitations: list[str] | None = None,
    ) -> Answer:
        return Answer(
            status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            text=text,
            retrieval_score=0.0,
            evidence_coverage=0.0,
            query_coverage=0.0,
            decision_reason=reason,
            calibration_id=self.audit_policy.calibration_id,
            limitations=["Генерацію зупинено fail-closed.", *(limitations or [])],
            corpus_release=release_id,
        )

    def audit(
        self,
        identity: Identity,
        query: QueryRequest,
        answer: Answer,
        retrieved: list[RetrievedEvidence],
        eligible: list[RetrievedEvidence],
        risk: QueryRisk,
        *,
        breaches: list[ScopeBreach] | None = None,
        support: SupportVerdict | None = None,
        plan: QueryPlan | None = None,
        composition: str | None = None,
        token: CorpusReadToken | None,
    ) -> None:
        append_answer_audit(
            self.repository,
            identity,
            query,
            answer,
            retrieved,
            eligible,
            risk,
            minimum_score=self.audit_policy.minimum_score,
            minimum_query_coverage=self.audit_policy.minimum_query_coverage,
            minimum_support_score=self.audit_policy.minimum_support_score,
            breaches=breaches,
            support=support,
            plan=plan,
            composition=composition,
            token=token,
        )


class SnapshotAnswerSession:
    """One token, one historical date, one authorization scope, one answer outcome."""

    def __init__(
        self,
        runtime: SnapshotAnswerRuntime,
        identity: Identity,
        query: QueryRequest,
        corpora: frozenset[str],
        token: CorpusReadToken,
    ) -> None:
        self.runtime = runtime
        self.identity = identity
        self.query = query
        self.corpora = corpora
        self.token = token

    @property
    def release_id(self) -> str:
        return self.token.release_id

    def search_plan(self, plan: QueryPlan, risk: QueryRisk) -> list[RetrievedEvidence]:
        best: dict[str, RetrievedEvidence] = {}
        try:
            for text in plan.searches:
                for item in self.runtime.retriever.search(
                    self.identity,
                    text,
                    self.corpora,
                    self.query.as_of,
                    self.token,
                ):
                    key = str(item.span.id)
                    previous = best.get(key)
                    if previous is None or item.score > previous.score:
                        best[key] = item
        except CorpusConsistencyError as exc:
            answer = self.runtime.abstain(
                self.release_id,
                "corpus_snapshot_changed",
                "Корпус змінився під час пошуку; результат відкинуто без переходу до нового стану.",
            )
            self.runtime.audit(
                self.identity,
                self.query,
                answer,
                [],
                [],
                risk,
                plan=plan,
                token=self.token,
            )
            raise SnapshotAnswerAbort(answer) from exc
        return sorted(
            best.values(),
            key=lambda item: (-item.score, -item.query_coverage, item.span.ordinal),
        )

    def finish(
        self,
        answer: Answer,
        retrieved: list[RetrievedEvidence],
        eligible: list[RetrievedEvidence],
        risk: QueryRisk,
        *,
        breaches: list[ScopeBreach] | None = None,
        support: SupportVerdict | None = None,
        plan: QueryPlan | None = None,
        composition: str | None = None,
    ) -> Answer:
        """Linearization point: stale or foreign-release work is discarded."""
        if answer.corpus_release != self.release_id:
            answer = self.runtime.abstain(
                self.release_id,
                "corpus_release_mismatch",
                "Внутрішня мітка релізу не відповідає зафіксованому стану корпусу; "
                "результат відкинуто.",
            )
            retrieved = []
            eligible = []
            breaches = None
            support = None
            composition = "discarded: answer release did not match snapshot token"
        try:
            self.runtime.snapshot_reader.validate(
                self.identity, self.corpora, self.query.as_of, self.token
            )
        except CorpusConsistencyError:
            answer = self.runtime.abstain(
                self.release_id,
                "corpus_snapshot_changed",
                "Корпус змінився до завершення відповіді; зібраний результат відкинуто.",
            )
            retrieved = []
            eligible = []
            breaches = None
            support = None
            composition = "discarded: corpus snapshot changed"
        self.runtime.audit(
            self.identity,
            self.query,
            answer,
            retrieved,
            eligible,
            risk,
            breaches=breaches,
            support=support,
            plan=plan,
            composition=composition,
            token=self.token,
        )
        return answer
