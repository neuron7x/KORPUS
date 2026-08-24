"""An answer may not be refuted by the span it cites.

Destruction stage B2 / §2.0.1 of ADMISSION_BOUNDARY_2026-08-03. The contradiction
detector compared the selected claim sentences against each other, so two spans that
disagreed reached `requires_human_review` — but a single span whose *next sentence*
reversed the one quoted did not. Reproduced: the answer asserted «обов'язкове», citing
a span in which the following sentence said «не обов'язкове», `status=answered`.

The reader who opens the source sees the reversal immediately. The system that pointed
them at it did not, which is worse than not answering: it spends the reader's trust to
deliver the half of the paragraph that happened to match their words.
"""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
from korpus.application.answer_query import ExtractiveAnswerService
from korpus.domain.models import (
    AuthorityClass,
    Citation,
    Claim,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    RetrievedEvidence,
    ReviewState,
    SupportState,
)

from apps.api.tests.helpers import approve, ingest_text

MARKER = "СУПЕРЕЧНІСТЬ"


def _evidence(text: str) -> RetrievedEvidence:
    document = DocumentRecord(
        canonical_title="Джерело",
        corpus_id="public",
        issuer="Authorized Test Authority",
        jurisdiction="UA",
        document_type="order",
        access_tier=0,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1.0",
        source_hash="ab" * 32,
        object_key="objects/x",
        mime_type="text/plain",
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.APPROVED,
    )
    span = EvidenceSpanRecord(version_id=version.id, ordinal=0, text=text)
    return RetrievedEvidence(
        span=span, document=document, version=version, score=0.9, query_coverage=1.0
    )


def test_a_span_that_reverses_itself_stops_the_answer(client: TestClient) -> None:
    """Both sentences live in one span; only the first matches the query."""
    body = (
        f"Ведення журналу {MARKER} є обов'язковим для кожного підрозділу. "
        f"Ведення журналу {MARKER} не є обов'язковим для підрозділів забезпечення."
    )
    result = ingest_text(client, text=body)
    approve(client, result["version"]["id"])

    answer = client.post(
        "/v1/answers", json={"text": f"чи обов'язкове ведення журналу {MARKER}"}
    ).json()

    assert answer["status"] == "requires_human_review", answer["decision_reason"]
    assert answer["decision_reason"] == "contradictory_authoritative_evidence"
    assert any("opposed_negation" in limitation for limitation in answer["limitations"]), answer[
        "limitations"
    ]


def test_a_numeric_reversal_inside_one_span_stops_the_answer(client: TestClient) -> None:
    """Not only negation: two incompatible quantities for the same subject."""
    body = (
        f"Строк подання донесення {MARKER} становить 24 год з моменту події. "
        f"Строк подання донесення {MARKER} становить 72 год для підрозділів забезпечення."
    )
    result = ingest_text(client, text=body)
    approve(client, result["version"]["id"])

    answer = client.post(
        "/v1/answers", json={"text": f"який строк подання донесення {MARKER}"}
    ).json()

    assert answer["status"] == "requires_human_review", answer["decision_reason"]
    assert answer["decision_reason"] == "contradictory_authoritative_evidence"


def test_the_scan_covers_eligible_spans_not_only_cited_ones() -> None:
    """Stated against the decision function, because end to end cannot separate them.

    Extraction takes at most one sentence per span and stops at `max_claims`, so a
    refutation can sit in a span that cleared every eligibility gate and still was not
    quoted. Driving that through HTTP is not reproducible on demand — which span the
    chunker forms and which sentence wins are not properties of the requirement — so
    the width of the scan is asserted where it is decided. A narrowing of the scan to
    citations passes every end-to-end test in this file and fails here.
    """
    quoted = _evidence(f"Ведення журналу {MARKER} є обов'язковим для кожного підрозділу.")
    unquoted = _evidence(
        f"Ведення журналу {MARKER} не є обов'язковим для підрозділів забезпечення."
    )
    claim = Claim(
        text=quoted.span.text,
        evidence_span_ids=(quoted.span.id,),
        support_state=SupportState.EXTRACTIVE,
        support_score=1.0,
        query_coverage=1.0,
    )
    citation = Citation(
        document_id=quoted.document.id,
        version_id=quoted.version.id,
        span_id=quoted.span.id,
        title=quoted.document.canonical_title,
        revision=quoted.version.revision,
        quote=quoted.span.text,
        quote_start=0,
        quote_end=len(quoted.span.text),
        quote_hash=hashlib.sha256(quoted.span.text.encode("utf-8")).hexdigest(),
        source_hash=quoted.version.source_hash,
    )

    reason = ExtractiveAnswerService._find_contradiction([claim], [citation], [quoted, unquoted])

    assert reason is not None and reason.startswith("refuted_by_evidence:"), (
        "a refutation in an eligible span the answer did not quote must still stop it"
    )


def test_an_unrelated_eligible_span_does_not_veto_the_answer() -> None:
    """The same width, exercised in the direction that must stay open."""
    quoted = _evidence(f"Ведення журналу {MARKER} є обов'язковим для кожного підрозділу.")
    unrelated = _evidence(
        "Бланки журналів видає служба матеріального забезпечення за окремою заявкою."
    )
    claim = Claim(
        text=quoted.span.text,
        evidence_span_ids=(quoted.span.id,),
        support_state=SupportState.EXTRACTIVE,
        support_score=1.0,
        query_coverage=1.0,
    )
    citation = Citation(
        document_id=quoted.document.id,
        version_id=quoted.version.id,
        span_id=quoted.span.id,
        title=quoted.document.canonical_title,
        revision=quoted.version.revision,
        quote=quoted.span.text,
        quote_start=0,
        quote_end=len(quoted.span.text),
        quote_hash=hashlib.sha256(quoted.span.text.encode("utf-8")).hexdigest(),
        source_hash=quoted.version.source_hash,
    )

    assert (
        ExtractiveAnswerService._find_contradiction([claim], [citation], [quoted, unrelated])
        is None
    )


def test_an_unrelated_neighbouring_sentence_does_not_block_the_answer(
    client: TestClient,
) -> None:
    """The negative control: a paragraph is not a contradiction because it is long.

    Without this the fix degenerates into abstaining on any span with more than one
    sentence, which is every real document — refusing everything is not evidence of
    correctness.
    """
    body = (
        f"Ведення журналу {MARKER} є обов'язковим для кожного підрозділу. "
        "Бланки журналів видає служба матеріального забезпечення за окремою заявкою."
    )
    result = ingest_text(client, text=body)
    approve(client, result["version"]["id"])

    answer = client.post(
        "/v1/answers", json={"text": f"чи обов'язкове ведення журналу {MARKER}"}
    ).json()

    assert answer["status"] == "answered", answer["decision_reason"]
