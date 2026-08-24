"""The application layer re-checks what the retrieval port hands back.

`Retriever` is a Protocol. The one adapter in the tree narrows the query in SQL, so
today the rows it returns are in scope — but nothing above it says so. A second
adapter, a cache keyed too loosely, or a defect in the single adapter would widen
disclosure and every layer above would treat the rows as authorized. `answer_query`
filtered on score, coverage, authority and review state; corpus and reader clearance
were not among them.

Cited here as `in-scope-rechecks-retriever` (ABSENT) and
`citing-above-reader-tier-is-breach` (WEAKER) in docs/audit/INVARIANT_DIFF_2026-08-03.md.

The check does not filter. A filter would answer from the remaining rows and leave a
defective adapter in service; the breach is a fact about the system, not about this
query, so the answer stops and the event is written to the audit chain.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from korpus.api.dependencies import get_answer_service
from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.policy import PolicyEngine
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    RetrievedEvidence,
    ReviewState,
)
from korpus.infrastructure.repository import audits
from sqlalchemy import select

from apps.api.tests.conftest import privileged_connection, set_identity

LEAK = "БЕТА-ВИТІК"


def _evidence(
    *,
    corpus_id: str = "public",
    access_tier: AccessTier = AccessTier.PUBLIC,
    classification: Classification = Classification.PUBLIC,
    compartments: frozenset[str] = frozenset(),
) -> RetrievedEvidence:
    document = DocumentRecord(
        canonical_title="Витік з чужої області",
        corpus_id=corpus_id,
        issuer="Authorized Test Authority",
        jurisdiction="UA",
        document_type="order",
        access_tier=access_tier,
        classification=classification,
        compartments=compartments,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1.0",
        source_hash="b" * 64,
        object_key="objects/leak",
        mime_type="text/plain",
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.APPROVED,
    )
    span = EvidenceSpanRecord(
        version_id=version.id,
        ordinal=0,
        text=f"Маркер {LEAK} не має покидати свою область доступу.",
    )
    return RetrievedEvidence(
        span=span,
        document=document,
        version=version,
        score=0.99,
        query_coverage=1.0,
    )


class LeakyRetriever:
    """A port implementation that ignores the scope it was asked for."""

    def __init__(self, evidence: RetrievedEvidence) -> None:
        self.evidence = evidence

    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int = 8,
    ) -> list[RetrievedEvidence]:
        return [self.evidence]


def _install(client: TestClient, evidence: RetrievedEvidence) -> None:
    service = ExtractiveAnswerService(
        client.app.state.repository,
        LeakyRetriever(evidence),
        PolicyEngine(),
        AnswerPolicy(
            minimum_score=0.08,
            minimum_query_coverage=0.15,
            minimum_support_score=0.08,
            calibration_id="test-scope",
        ),
    )
    client.app.dependency_overrides[get_answer_service] = lambda: service


def _ask(client: TestClient) -> dict[str, object]:
    response = client.post("/v1/answers", json={"text": f"де згадано {LEAK}"})
    assert response.status_code == 200, response.text
    payload: dict[str, object] = response.json()
    return payload


def _audit_actions(client: TestClient) -> list[str]:
    with privileged_connection(client) as connection:
        rows = connection.execute(select(audits.c.action, audits.c.payload_json)).all()
    return [row.action for row in rows]


@pytest.mark.parametrize(
    ("kwargs", "kind"),
    [
        ({"corpus_id": "restricted-demo"}, "corpus_out_of_scope"),
        (
            {"access_tier": AccessTier.RESTRICTED, "classification": Classification.RESTRICTED},
            "reader_not_cleared",
        ),
        ({"compartments": frozenset({"alpha"})}, "reader_not_cleared"),
    ],
)
def test_out_of_scope_evidence_stops_the_answer(
    client: TestClient, public_identity: Identity, kwargs: dict[str, object], kind: str
) -> None:
    _install(client, _evidence(**kwargs))  # type: ignore[arg-type]
    set_identity(client, public_identity)

    answer = _ask(client)

    assert answer["status"] == "requires_human_review", (
        "evidence outside the reader's scope is an integrity breach, not thin coverage"
    )
    assert answer["decision_reason"] == "retriever_scope_breach"
    assert answer["citations"] == []
    assert answer["claims"] == []
    assert LEAK not in json.dumps(answer, ensure_ascii=False), (
        "the leaked text must not reach the reader through the abstention either"
    )
    assert any(kind in str(limitation) for limitation in answer["limitations"])  # type: ignore[union-attr]


def test_the_breach_is_written_to_the_audit_chain(
    client: TestClient, public_identity: Identity
) -> None:
    _install(client, _evidence(corpus_id="restricted-demo"))
    set_identity(client, public_identity)

    _ask(client)

    actions = _audit_actions(client)
    assert "answer.scope_breach" in actions, (
        "a disclosure defect that leaves no trace cannot be investigated"
    )
    assert client.app.state.repository.verify_audit().valid


def test_in_scope_evidence_still_answers(client: TestClient, admin_identity: Identity) -> None:
    """The guard must not swallow the normal path: same shape, authorized document."""
    _install(client, _evidence())
    set_identity(client, admin_identity)

    answer = _ask(client)

    assert answer["status"] == "answered", answer["decision_reason"]
    assert answer["citations"]


def test_one_out_of_scope_row_stops_an_otherwise_valid_batch(
    client: TestClient, public_identity: Identity
) -> None:
    """Majority-in-scope is not a defence: the breach is about the port, not the batch."""
    authorized = _evidence()
    leaked = _evidence(corpus_id="restricted-demo")

    class MixedRetriever(LeakyRetriever):
        def search(
            self,
            identity: Identity,
            text: str,
            corpus_ids: frozenset[str],
            as_of: date,
            limit: int = 8,
        ) -> list[RetrievedEvidence]:
            return [authorized, leaked]

    service = ExtractiveAnswerService(
        client.app.state.repository,
        MixedRetriever(authorized),
        PolicyEngine(),
        AnswerPolicy(
            minimum_score=0.08,
            minimum_query_coverage=0.15,
            minimum_support_score=0.08,
            calibration_id="test-scope",
        ),
    )
    client.app.dependency_overrides[get_answer_service] = lambda: service
    set_identity(client, public_identity)

    answer = _ask(client)

    assert answer["status"] == "requires_human_review"
    assert answer["citations"] == []
