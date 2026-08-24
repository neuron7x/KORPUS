"""Rank is a class, not a quantity, and two live versions of one order are a conflict.

Authority was one term of a convex sum with weight 0.14. The prior gap between
OFFICIAL_UA and ANALYTICAL is 0.0756, so a lexically better-matched analytical passage
outranked the official order — and, once both were cited, could contradict it and push
the whole answer to REQUIRES_HUMAN_REVIEW. A source that cannot overrule another must
not be able to veto it either.

Separately, contradiction detection was textual and numeric only: two approved, live
versions of the same document that differ in a date or an annex reference passed
silently, and the answer cited whichever ranked higher — a decision the system is not
entitled to make.

`authority-outranks-score`, `conflict-confined-to-top-rank`, `conflict-keyed-on-version`
and `dedup-one-span-per-version` in docs/audit/INVARIANT_DIFF_2026-08-03.md.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from korpus.api.dependencies import get_answer_service
from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.policy import PolicyEngine
from korpus.application.retrieval import diversify_evidence
from korpus.domain.models import (
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    RetrievedEvidence,
    ReviewState,
)

from apps.api.tests.helpers import approve, ingest_text, ingest_version

QUESTION = "скільки записів за добу вносить підрозділ до журналу перевірок"
OFFICIAL = "Підрозділ вносить до журналу перевірок не менше 3 записів за добу."
ANALYTICAL = "Підрозділ вносить до журналу перевірок не менше 9 записів за добу за спостереженнями."


def _ask(client: TestClient) -> dict[str, object]:
    response = client.post("/v1/answers", json={"text": QUESTION})
    assert response.status_code == 200, response.text
    payload: dict[str, object] = response.json()
    return payload


def _evidence(
    authority: AuthorityClass, score: float, *, version: DocumentVersionRecord | None = None
) -> RetrievedEvidence:
    document = DocumentRecord(
        canonical_title=f"Джерело {authority.value}",
        corpus_id="public",
        issuer="Authorized Test Authority",
        jurisdiction="UA",
        document_type="order",
        access_tier=0,
        classification=Classification.PUBLIC,
    )
    version = version or DocumentVersionRecord(
        document_id=document.id,
        revision="1.0",
        source_hash=f"{ord(authority.value[0]):02x}" * 32,
        object_key="objects/x",
        mime_type="text/plain",
        authority=authority,
        review_state=ReviewState.APPROVED,
    )
    span = EvidenceSpanRecord(
        version_id=version.id, ordinal=0, text=f"Текст джерела {uuid4()} про журнал перевірок."
    )
    return RetrievedEvidence(
        span=span, document=document, version=version, score=score, query_coverage=1.0
    )


def test_similarity_cannot_promote_a_weaker_source_above_a_stronger_one() -> None:
    """Selection is lexicographic: authority class first, marginal relevance inside it."""
    analytical = _evidence(AuthorityClass.ANALYTICAL, 0.99)
    official = _evidence(AuthorityClass.OFFICIAL_UA, 0.20)

    selected = diversify_evidence([analytical, official], limit=1)

    assert [item.version.authority for item in selected] == [AuthorityClass.OFFICIAL_UA], (
        "an analytical passage scoring 0.99 must still rank below an official one at "
        "0.20; otherwise authority is a quantity similarity can outbid"
    )


def test_one_version_is_selected_once_however_many_spans_match() -> None:
    """Two quotes from one version are one source, not two."""
    version = DocumentVersionRecord(
        document_id=uuid4(),
        revision="1.0",
        source_hash="c" * 64,
        object_key="objects/x",
        mime_type="text/plain",
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.APPROVED,
    )
    first = _evidence(AuthorityClass.OFFICIAL_UA, 0.90, version=version)
    second = _evidence(AuthorityClass.OFFICIAL_UA, 0.80, version=version)

    selected = diversify_evidence([first, second], limit=4)

    assert len(selected) == 1, "per_version_cap defaults to one span per version"


def test_the_running_configuration_cites_one_span_per_version(client: TestClient) -> None:
    """The wired-up default, not just the function default.

    `diversify_evidence` defends its own signature above; this asserts what the
    application actually runs with, which is a separate value in `dependencies` and
    drifted from it before.
    """
    filler = "Технічні положення інструкції не стосуються обліку записів. " * 30
    result = ingest_text(
        client,
        title="Наказ про журнал",
        text="\n\n".join(
            [
                OFFICIAL,
                filler,
                "Кожен запис журналу перевірок за добу підписує відповідальний підрозділу.",
            ]
        ),
    )
    approve(client, result["version"]["id"])

    answer = _ask(client)

    assert answer["status"] == "answered", answer["decision_reason"]
    version_ids = [citation["version_id"] for citation in answer["citations"]]  # type: ignore[union-attr]
    assert len(version_ids) == len(set(version_ids)), (
        "two spans of one version were cited as two sources"
    )


def test_a_better_matched_analytical_source_is_not_cited_beside_an_official_one(
    client: TestClient,
) -> None:
    official = ingest_text(client, title="Наказ про журнал", text=OFFICIAL)
    approve(client, official["version"]["id"])
    analytical = ingest_text(
        client,
        title="Аналітична записка про журнал",
        authority="analytical",
        revision="1.1",
        text=ANALYTICAL,
    )
    approve(client, analytical["version"]["id"])

    answer = _ask(client)

    assert answer["status"] == "answered", answer["decision_reason"]
    cited_versions = {citation["version_id"] for citation in answer["citations"]}  # type: ignore[union-attr]
    assert cited_versions == {official["version"]["id"]}
    assert any("нижчого рангу" in str(limitation) for limitation in answer["limitations"])  # type: ignore[union-attr]


def test_a_lower_ranked_source_cannot_veto_the_answer(client: TestClient) -> None:
    """The analytical note contradicts the order numerically; the order still answers."""
    official = ingest_text(client, title="Наказ про журнал", text=OFFICIAL)
    approve(client, official["version"]["id"])
    analytical = ingest_text(
        client,
        title="Аналітична записка про журнал",
        authority="analytical",
        revision="1.1",
        text=ANALYTICAL,
    )
    approve(client, analytical["version"]["id"])

    answer = _ask(client)

    assert answer["decision_reason"] == "extractive_claims_passed_calibrated_gates", (
        "a source that cannot overrule the order cannot block it either"
    )
    assert "9 записів" not in str(answer["text"])


def test_approval_refuses_a_second_current_version_of_one_document(
    client: TestClient,
) -> None:
    """Ingestion is the first line: a new version must say what it supersedes."""
    first = ingest_text(client, title="Наказ про журнал", text=OFFICIAL)
    approve(client, first["version"]["id"])
    second = ingest_version(
        client,
        first["document"]["id"],
        revision="2.0",
        text="Підрозділ вносить до журналу перевірок не менше 3 записів щодоби.",
    )

    for target in ("metadata_reviewed", "content_reviewed"):
        response = client.post(
            f"/v1/document-versions/{second['version']['id']}/review",
            json={
                "target": target,
                "note": f"independent verification completed for transition {target}",
                "acknowledge_near_duplicate": True,
                "acknowledge_extraction_quality": True,
            },
        )
        assert response.status_code == 200, response.text
    refusal = client.post(
        f"/v1/document-versions/{second['version']['id']}/review",
        json={"target": "approved", "note": "approval without a supersession edge"},
    )

    assert refusal.status_code == 409, refusal.text
    assert "supersede" in refusal.json()["detail"]


def test_two_live_versions_of_one_document_require_a_human(client: TestClient) -> None:
    """And the answer layer does not assume ingestion held.

    Approval refuses a second current version today, but the state is reachable by
    branching supersession, by a restore that replays an older edge, or by any second
    write path added later. Which version governs is not a question ranking may answer,
    so the answer layer checks it too — one document, two cited versions, no answer.
    """
    first = ingest_text(client, title="Наказ про журнал", text=OFFICIAL)
    approve(client, first["version"]["id"])
    repository = client.app.state.repository
    rows = repository.list_retrievable_spans(
        client.identity_provider.current, frozenset({"public"}), date.today()
    )
    span, document, version = rows[0]
    sibling = version.model_copy(update={"id": uuid4(), "revision": "2.0"}, deep=True)
    sibling_span = EvidenceSpanRecord(
        version_id=sibling.id,
        ordinal=0,
        text="Підрозділ вносить до журналу перевірок не менше 3 записів щодоби.",
    )

    class TwoVersionRetriever:
        def search(
            self,
            identity: Identity,
            text: str,
            corpus_ids: frozenset[str],
            as_of: date,
            limit: int = 8,
        ) -> list[RetrievedEvidence]:
            return [
                RetrievedEvidence(
                    span=span, document=document, version=version, score=0.9, query_coverage=1.0
                ),
                RetrievedEvidence(
                    span=sibling_span,
                    document=document,
                    version=sibling,
                    score=0.85,
                    query_coverage=1.0,
                ),
            ]

    service = ExtractiveAnswerService(
        repository,
        TwoVersionRetriever(),
        PolicyEngine(),
        AnswerPolicy(
            minimum_score=0.08,
            minimum_query_coverage=0.15,
            minimum_support_score=0.08,
            calibration_id="test-versions",
        ),
    )
    client.app.dependency_overrides[get_answer_service] = lambda: service

    answer = _ask(client)

    assert answer["status"] == "requires_human_review", (
        "two live versions of one document is a corpus state the system may not resolve by ranking"
    )
    assert "multiple_current_versions" in str(answer["limitations"])


def test_the_retriever_carries_the_same_cap_its_diversifier_defaults_to() -> None:
    """Two defaults for one decision, and production uses neither.

    `diversify_evidence(per_version_cap=1)` and `HybridLexicalRetriever(per_version_cap=1)`
    are separate literals. `dependencies.py` passes the value explicitly from the
    calibration profile, so the retriever's default is never exercised in production —
    which means it can drift from the function it forwards to and nothing observes it.

    Found 2026-08-06: a single mutant covered both literals, so a test of either answered
    for the pair and neither was individually falsified. Asserting they agree is the
    cheapest thing that makes the drift visible; removing one of them is the real fix and
    is recorded in TECHNICAL_DEBT_V5.md.
    """
    import inspect

    from korpus.application.retrieval import HybridLexicalRetriever, diversify_evidence

    function_default = inspect.signature(diversify_evidence).parameters["per_version_cap"].default
    retriever_default = (
        inspect.signature(HybridLexicalRetriever.__init__).parameters["per_version_cap"].default
    )

    assert function_default == retriever_default == 1
