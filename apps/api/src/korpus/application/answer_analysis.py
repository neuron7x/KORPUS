"""Pure/side-effect-isolated analysis used by the extractive answer orchestrator.

This module deliberately does not own the order of answer gates. `ExtractiveAnswerService`
keeps that sequence explicit; these functions only evaluate one bounded predicate or
projection at a time.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from korpus.application.evidence import (
    assess_control_injection,
    contradiction_reason,
    refuting_sentence,
    segment_sentences,
)
from korpus.application.policy import PolicyEngine
from korpus.application.retrieval import AUTHORITY_PRIOR, tokenize
from korpus.domain.models import Citation, Claim, Identity, RetrievedEvidence


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


def scope_breaches(
    identity: Identity,
    corpora: frozenset[str],
    retrieved: list[RetrievedEvidence],
    policy_engine: PolicyEngine,
) -> list[ScopeBreach]:
    """Fail-closed re-check of the retriever's claimed authorization scope."""
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
        decision = policy_engine.can_access_document(identity, document)
        if not decision.allowed:
            breaches.append(ScopeBreach(version_id, "reader_not_cleared", decision.reason))
    return breaches


def unsourced_quotes(
    eligible: list[RetrievedEvidence], citations: list[Citation]
) -> list[str]:
    """Return citation span ids whose quote is not verbatim in the named span."""
    span_text = {str(item.span.id): item.span.text for item in eligible}
    return [
        str(citation.span_id)
        for citation in citations
        if citation.quote not in span_text.get(str(citation.span_id), "")
    ]


def source_limitations(
    citations: list[Citation],
    outranked: list[RetrievedEvidence],
    used: list[RetrievedEvidence],
) -> list[str]:
    """Name ranking exclusions, repeated sources and absent publication dates."""
    limitations: list[str] = []
    undated = {item.version.id for item in used if item.version.publication_date is None}
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


def confine_to_top_authority(
    eligible: list[RetrievedEvidence],
) -> tuple[list[RetrievedEvidence], list[RetrievedEvidence]]:
    if not eligible:
        return [], []
    top = max(AUTHORITY_PRIOR[item.version.authority] for item in eligible)
    confined = [item for item in eligible if AUTHORITY_PRIOR[item.version.authority] == top]
    outranked = [item for item in eligible if AUTHORITY_PRIOR[item.version.authority] < top]
    return confined, outranked


def find_contradiction(
    claims: list[Claim],
    citations: list[Citation],
    eligible: list[RetrievedEvidence],
) -> str | None:
    """Detect version, claim-level and whole-evidence contradictions."""
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


def quote_hash(text: str) -> str:
    """Named primitive retained for callers that need the exact citation hash rule."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
