"""Coverage counts statements; a statement pointing outside its own citations counts for none.

`evidence_coverage` was `len(citations) / len(claims)`. That denominator is claims but
the numerator is documents, so the ratio answered a question nobody asked: two
citations on one claim read as 2.0 and tripped `le=1` inside the response model, which
surfaces as a 500 — an unhandled crash standing in for an abstention. In the other
direction a claim citing a span the answer does not carry was never checked at all.

`coverage-denominator-is-claims` (WEAKER), `citation-evidence-misalignment-fails-closed`
(ABSENT) and `partial-invalid-index-gives-no-credit` (ABSENT) in
docs/audit/INVARIANT_DIFF_2026-08-03.md.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from korpus.api.dependencies import get_answer_service
from korpus.application.answer_query import ExtractiveAnswerService
from korpus.application.evidence import verify_claim_support
from korpus.application.policy import PolicyEngine
from korpus.application.risk import RiskThresholds
from korpus.config import get_settings
from korpus.domain.models import Citation, Claim, Identity, RetrievedEvidence

from apps.api.tests.helpers import approve, ingest_text

MARKER = "ЗЧЕПЛЕННЯ"
BODY = f"Маркер {MARKER} присутній у затвердженому джерелі та підлягає цитуванню."


def test_every_claim_backed_by_a_carried_citation_is_full_coverage() -> None:
    first, second = uuid4(), uuid4()

    verdict = verify_claim_support([(0, [first]), (1, [second])], [first, second])

    assert verdict.coverage == 1.0
    assert verdict.aligned


def test_extra_citations_do_not_push_coverage_above_one() -> None:
    """The old ratio returned 2.0 here and the response model raised on it."""
    span = uuid4()

    verdict = verify_claim_support([(0, [span])], [span, uuid4(), uuid4()])

    assert verdict.coverage == 1.0, "coverage is a fraction of claims, not a citation count"
    assert verdict.aligned


def test_a_claim_referencing_an_uncarried_span_gets_no_credit() -> None:
    carried = uuid4()

    verdict = verify_claim_support([(0, [carried]), (1, [uuid4()])], [carried])

    assert verdict.coverage == 0.5
    assert verdict.unsupported_claim_indexes == (1,)
    assert "out_of_range" in verdict.reasons[0]


def test_partially_valid_references_earn_nothing_for_that_claim() -> None:
    """One good span id plus one bad one is not half a proof."""
    carried = uuid4()

    verdict = verify_claim_support([(0, [carried, uuid4()])], [carried])

    assert verdict.coverage == 0.0
    assert verdict.unsupported_claim_indexes == (0,)


def test_a_claim_with_no_reference_at_all_is_unsupported() -> None:
    verdict = verify_claim_support([(0, [])], [uuid4()])

    assert verdict.coverage == 0.0
    assert "no evidence reference" in verdict.reasons[0]


def test_no_claims_is_zero_coverage_not_a_division_error() -> None:
    verdict = verify_claim_support([], [])

    assert verdict.coverage == 0.0
    assert verdict.aligned


class MisalignedService(ExtractiveAnswerService):
    """An extraction that emits one claim more than it can cite."""

    def _extract(
        self,
        eligible: list[RetrievedEvidence],
        query_tokens: frozenset[str],
        thresholds: RiskThresholds,
    ) -> tuple[list[Claim], list[Citation], set[str]]:
        claims, citations, covered = super()._extract(eligible, query_tokens, thresholds)
        if claims:
            claims.append(claims[0].model_copy(update={"evidence_span_ids": (uuid4(),)}, deep=True))
        return claims, citations, covered


def test_a_misaligned_answer_stops_instead_of_raising(
    client: TestClient, admin_identity: Identity
) -> None:
    """The failure mode this replaces was a 500, not an abstention."""
    result = ingest_text(client, text=BODY)
    approve(client, result["version"]["id"])
    real = get_answer_service(
        client.app.state.repository,
        PolicyEngine(),
        client.app.dependency_overrides[get_settings](),
        client.app.state.query_cache,
        client.app.state.semantic_source,
    )
    service = MisalignedService(
        client.app.state.repository,
        real.retriever,
        PolicyEngine(),
        real.answer_policy,
    )
    client.app.dependency_overrides[get_answer_service] = lambda: service

    response = client.post("/v1/answers", json={"text": f"де згадано {MARKER}"})

    assert response.status_code == 200, "misalignment must abstain, not crash the request"
    answer = response.json()
    assert answer["status"] == "requires_human_review"
    assert answer["decision_reason"] == "citation_evidence_misalignment"
    assert answer["evidence_coverage"] == 0.0
    assert answer["claims"] == []
    assert answer["citations"] == []


def test_the_aligned_path_reports_coverage_by_claim(
    client: TestClient, admin_identity: Identity
) -> None:
    result = ingest_text(client, text=BODY)
    approve(client, result["version"]["id"])

    answer = client.post("/v1/answers", json={"text": f"де згадано {MARKER}"}).json()

    assert answer["status"] == "answered", answer["decision_reason"]
    assert answer["evidence_coverage"] == 1.0
    assert len(answer["claims"]) == len(answer["citations"])
