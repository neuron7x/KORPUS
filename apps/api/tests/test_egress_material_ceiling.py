"""What may be sent to a model outside the deployment is decided by classification.

GOV-006. Two optional model calls exist; one of them, the composer, is handed the
retrieved sentences themselves. Under `external_allowed` that reaches a vendor, and the
vendor sees whatever it is sent — so a restricted corpus answered under that posture
exfiltrates restricted spans to the vendor, whatever the composer returns. The URL check
in `korpus.application.egress` governs whether an endpoint may be reached; it says nothing
about the classification of what is then sent to it.

The property proved here is the one that matters: a composer never receives material above
the egress ceiling. The negative control is the same test run with public material, where
the composer *is* called — a gate that refused everything would pass the security assertion
and be useless, so both directions are asserted, and so is each posture that changes the
answer.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.egress import EgressPosture, ModelEgressPolicy
from korpus.domain.models import (
    AccessTier,
    Identity,
    QueryRequest,
    RetrievedEvidence,
)

from apps.api.tests.helpers import approve, ingest_text

SENTENCE = "Кожен запис журналу має містити дату та відповідальну особу."


class _SpyComposer:
    """Records what it was handed. A refused opening keeps the extract untouched, which is
    fine — the assertion is on whether the material reached it at all, not on the shape of
    what came back."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def compose(self, question: str, sentences: list[str]) -> tuple[str, list[str]]:
        self.calls.append(list(sentences))
        # An opening made of words that are in the evidence, so composition succeeds and
        # the positive control observes a real arrangement rather than a refusal.
        return "Кожен запис має містити дату", list(sentences)


def _evidence_at(client: TestClient, tier: int) -> RetrievedEvidence:
    result = ingest_text(client, access_tier=tier, text=SENTENCE)
    approve(client, result["version"]["id"])
    rows = client.app.state.repository.list_retrievable_spans(
        client.identity_provider.current, frozenset({"public"}), date.today()
    )
    span, document, version = rows[0]
    assert int(document.access_tier) == tier
    return RetrievedEvidence(
        span=span, document=document, version=version, score=0.95, query_coverage=1.0
    )


def _run(
    client: TestClient,
    identity: Identity,
    tier: int,
    posture: EgressPosture,
    ceiling: AccessTier,
) -> tuple[_SpyComposer, object]:
    evidence = _evidence_at(client, tier)

    class _Retriever:
        def search(
            self,
            _identity: Identity,
            _text: str,
            _corpus_ids: frozenset[str],
            _as_of: date,
            limit: int = 8,
        ) -> list[RetrievedEvidence]:
            return [evidence]

    spy = _SpyComposer()
    service = ExtractiveAnswerService(
        client.app.state.repository,
        _Retriever(),
        client.app.state.policy,
        AnswerPolicy(
            minimum_score=0.05,
            minimum_query_coverage=0.1,
            minimum_support_score=0.05,
            calibration_id="egress-ceiling-test",
        ),
        answer_composer=spy,
        egress_policy=ModelEgressPolicy(posture, max_external_tier=ceiling),
    )
    answer = service.execute(identity, QueryRequest(text="Що має містити запис журналу?"))
    return spy, answer


def test_restricted_material_never_reaches_an_external_composer(
    client: TestClient, admin_identity: Identity
) -> None:
    spy, answer = _run(
        client,
        admin_identity,
        tier=int(AccessTier.RESTRICTED),
        posture=EgressPosture.EXTERNAL_ALLOWED,
        ceiling=AccessTier.PUBLIC,
    )
    assert spy.calls == [], "restricted spans were sent to a model outside the deployment"
    # The answer still stands — extractive, unarranged. The opening the composer would
    # have proposed is absent, which is the observable trace of the refusal.
    assert answer.status.value == "answered"
    assert answer.opening == ""


def test_public_material_does_reach_the_composer(
    client: TestClient, admin_identity: Identity
) -> None:
    """The negative control. A ceiling that refused everything would pass the test above
    and disable a working feature; this proves it refuses by classification, not always."""
    spy, answer = _run(
        client,
        admin_identity,
        tier=int(AccessTier.PUBLIC),
        posture=EgressPosture.EXTERNAL_ALLOWED,
        ceiling=AccessTier.PUBLIC,
    )
    assert len(spy.calls) == 1, "public material was withheld from the composer"
    assert answer.opening == "Кожен запис має містити дату"


def test_local_only_carries_restricted_material_because_it_never_leaves(
    client: TestClient, admin_identity: Identity
) -> None:
    """The ceiling governs egress, and `local_only` is not egress: the model is inside the
    deployment, so restricted material may be arranged by it."""
    spy, _ = _run(
        client,
        admin_identity,
        tier=int(AccessTier.RESTRICTED),
        posture=EgressPosture.LOCAL_ONLY,
        ceiling=AccessTier.PUBLIC,
    )
    assert len(spy.calls) == 1


def test_a_raised_ceiling_admits_material_up_to_it(
    client: TestClient, admin_identity: Identity
) -> None:
    """Raising the ceiling is the deliberate GOV-006 act that lets restricted material be
    sent to a vendor — the difference between a default and a decision."""
    spy, _ = _run(
        client,
        admin_identity,
        tier=int(AccessTier.RESTRICTED),
        posture=EgressPosture.EXTERNAL_ALLOWED,
        ceiling=AccessTier.RESTRICTED,
    )
    assert len(spy.calls) == 1


def test_permits_material_is_a_ceiling_not_a_floor() -> None:
    """`<=` and not `<`: material *at* the ceiling is admitted, material above is not."""
    policy = ModelEgressPolicy(
        EgressPosture.EXTERNAL_ALLOWED, max_external_tier=AccessTier.AUTHENTICATED
    )
    assert policy.permits_material(AccessTier.PUBLIC)
    assert policy.permits_material(AccessTier.AUTHENTICATED)
    assert not policy.permits_material(AccessTier.REVIEWED)
    assert not policy.permits_material(AccessTier.RESTRICTED)


def test_permits_material_ignores_the_ceiling_when_the_model_is_local() -> None:
    for posture in (EgressPosture.LOCAL_ONLY, EgressPosture.MODEL_DISABLED):
        policy = ModelEgressPolicy(posture, max_external_tier=AccessTier.PUBLIC)
        assert policy.permits_material(AccessTier.RESTRICTED), posture


def test_a_claim_backed_by_an_unknown_span_is_treated_as_the_most_restrictive(
    client: TestClient,
) -> None:
    """The one place a guess is a leak. A span whose tier the eligible set does not carry
    is assumed RESTRICTED, so a composer cannot be reached by a claim whose provenance the
    service cannot see — the opposite default would send unknown material to a vendor."""
    from uuid import uuid4

    from korpus.domain.models import Claim

    service = ExtractiveAnswerService(
        client.app.state.repository,
        _StubRetriever(),
        client.app.state.policy,
        AnswerPolicy(0.05, 0.1, 0.05, "unknown-span-test"),
        egress_policy=ModelEgressPolicy(
            EgressPosture.EXTERNAL_ALLOWED, max_external_tier=AccessTier.PUBLIC
        ),
    )
    orphan = Claim(
        text=SENTENCE,
        evidence_span_ids=(uuid4(),),
        support_score=1.0,
        query_coverage=1.0,
    )
    assert service._composition_egress_permitted([orphan], []) is False


class _StubRetriever:
    def search(self, *args: object, **kwargs: object) -> list[RetrievedEvidence]:
        return []
