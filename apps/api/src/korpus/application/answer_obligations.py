"""Independent pre-answer applicability check over the actual emitted claims."""

from __future__ import annotations

from korpus.application.declared_subject import subject_tokens
from korpus.application.question_obligations import QuestionObligations, question_obligations
from korpus.application.retrieval_math import tokenize
from korpus.domain.models import Citation, Claim, RetrievedEvidence


def _claim_citations_bound(claims: list[Claim], citations: list[Citation]) -> bool:
    claimed = {(claim.text, span_id) for claim in claims for span_id in claim.evidence_span_ids}
    cited = {(citation.quote, citation.span_id) for citation in citations}
    return all(claim.evidence_span_ids for claim in claims) and claimed == cited


def _bound_quote(citation: Citation, claims: list[Claim], item: RetrievedEvidence | None) -> bool:
    return (
        item is not None
        and citation.version_id == item.version.id
        and citation.document_id == item.document.id
        and any(
            claim.text == citation.quote and citation.span_id in claim.evidence_span_ids
            for claim in claims
        )
    )


def _unmet_facets(
    obligations: QuestionObligations, covered: dict[str, set[int]]
) -> tuple[str, ...]:
    required = set(range(len(obligations.facets)))
    if required and not any(required <= value for value in covered.values()):
        best = max(
            covered.values(), key=lambda value: (len(value), tuple(sorted(value))), default=set()
        )
        return tuple(obligations.facets[index].label for index in sorted(required - best))
    return ()


def unmet_answer_obligations(
    question: str,
    claims: list[Claim],
    citations: list[Citation],
    eligible: list[RetrievedEvidence],
) -> tuple[str, ...]:
    if not _claim_citations_bound(claims, citations):
        return ("claim_quote_binding",)
    obligations = question_obligations(question)
    if obligations.overflow:
        return ("question_obligation_budget_exceeded",)
    if obligations.ambiguous_label:
        return ("ambiguous_single_letter_subject",)
    evidence = {item.span.id: item for item in eligible}
    query_tokens = frozenset(tokenize(question))
    failures: set[str] = set()
    covered: dict[str, set[int]] = {}
    for citation in citations:
        item = evidence.get(citation.span_id)
        if not _bound_quote(citation, claims, item):
            failures.add("claim_quote_binding")
            continue
        assert item is not None
        declared = frozenset(
            subject_tokens([item.document.canonical_title]).intersection(query_tokens)
        )
        failures.update(obligations.missing_subjects(citation.quote, declared))
        hits = obligations.facet_hits(citation.quote, declared)
        if obligations.facets and not hits:
            failures.add("question_fact_binding")
        covered.setdefault(str(citation.version_id), set()).update(hits)
    if not citations:
        failures.update(item.label for item in obligations.subjects)
    failures.update(_unmet_facets(obligations, covered))
    return tuple(sorted(failures))
