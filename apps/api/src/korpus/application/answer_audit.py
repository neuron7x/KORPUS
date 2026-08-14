"""Stable audit serialization for answer decisions."""
from __future__ import annotations

import hashlib

from korpus.application.answer_analysis import ScopeBreach
from korpus.application.corpus_snapshot import CorpusReadToken, token_audit_record
from korpus.application.evidence import SupportVerdict
from korpus.application.ports import Repository
from korpus.application.query_plan import QueryPlan
from korpus.application.risk import QueryRisk, risk_adjusted_thresholds
from korpus.domain.models import Answer, Identity, QueryRequest, RetrievedEvidence


def append_answer_audit(
    repository: Repository,
    identity: Identity,
    query: QueryRequest,
    answer: Answer,
    retrieved: list[RetrievedEvidence],
    eligible: list[RetrievedEvidence],
    risk: QueryRisk,
    *,
    minimum_score: float,
    minimum_query_coverage: float,
    minimum_support_score: float,
    breaches: list[ScopeBreach] | None = None,
    support: SupportVerdict | None = None,
    plan: QueryPlan | None = None,
    composition: str | None = None,
    token: CorpusReadToken | None = None,
) -> None:
    if support is not None and not support.aligned:
        repository.append_audit(
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
        repository.append_audit(
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
        minimum_score=minimum_score,
        minimum_query_coverage=minimum_query_coverage,
        minimum_support_score=minimum_support_score,
    )
    repository.append_audit(
        identity,
        "answer.completed",
        "answer",
        str(answer.id),
        {
            "status": answer.status.value,
            "decision_reason": answer.decision_reason,
            "query_hash": hashlib.sha256(query.text.encode("utf-8")).hexdigest(),
            "requested_corpora": query.corpus_ids,
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
            "query_plan": plan.as_audit_record() if plan is not None else None,
            "composition": composition,
            "retrieved": len(retrieved),
            "eligible": len(eligible),
            "citation_count": len(answer.citations),
            "evidence_coverage": answer.evidence_coverage,
            "query_coverage": answer.query_coverage,
            "retrieval_score_kind": answer.retrieval_score_kind,
            "calibration_id": answer.calibration_id,
            "corpus_release": answer.corpus_release,
            "corpus_snapshot": token_audit_record(token),
            "query_risk": risk.value,
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
