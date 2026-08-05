"""The support gate has to be able to reject something.

Destruction stage, MAJOR: `support_score` was the constant 1.0 and the risk-adjusted
thresholds are clamped to at most 1.0, so `support_score < minimum_support_score` was
false in every configuration. The branch was unreachable, `SupportState.UNSUPPORTED`
was produced nowhere, and deleting the two lines changed no test. A predicate that
cannot be false is not a safeguard; it is a claim about one.

The measure is the share of a claim's content tokens present in its cited span. For a
byte-for-byte extract that is 1.0 by construction — deliberately, so the number does
not drift while extraction is exact — and it falls the moment a claim carries anything
its span does not, which is the case the gate exists for.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from korpus.api.dependencies import get_answer_service
from korpus.application.answer_query import (
    AnswerPolicy,
    ExtractiveAnswerService,
    SentenceCandidate,
)
from korpus.application.evidence import extractive_support
from korpus.application.policy import PolicyEngine
from korpus.config import get_settings

from apps.api.tests.helpers import approve, ingest_text

MARKER = "ПІДТРИМКА"
BODY = f"Журнал {MARKER} ведеться щодоби відповідальною особою підрозділу."


def test_a_verbatim_extract_is_fully_supported() -> None:
    assert extractive_support(BODY, BODY) == 1.0


def test_a_claim_the_span_does_not_carry_is_not_fully_supported() -> None:
    score = extractive_support(
        "Журнал знищується негайно після завершення операції", BODY
    )

    assert 0.0 <= score < 1.0, score


def test_an_empty_claim_has_no_support() -> None:
    """Zero, not one: nothing is not trivially supported by everything."""
    assert extractive_support("   ", BODY) == 0.0


class DriftingService(ExtractiveAnswerService):
    """Extraction that emits a sentence its span does not contain.

    The gate guards against extraction ceasing to be exact — a re-written generator, a
    normalisation step, a summarising provider. None of those exist yet, so the case is
    produced by substitution rather than waited for.
    """

    def _candidates(self, text: str, query_tokens: frozenset[str]):  # type: ignore[no-untyped-def]
        del text
        invented = (
            f"Журнал {MARKER} підлягає негайному знищенню за розпорядженням чергового"
            " офіцера оперативного відділу."
        )
        return [
            SentenceCandidate(
                text=invented, start=0, end=len(invented), query_coverage=1.0
            )
        ]


def test_the_extraction_step_drops_a_claim_below_the_support_threshold() -> None:
    """Stated at the layer that decides, because a second line masks it end to end.

    A drifting claim that survives this gate is caught downstream by the check that a
    quote must be a substring of its span (§2.0), and the answer is withheld either
    way. So the behavioural test cannot tell a measured `support_score` from the
    constant 1.0, and a mutation to the constant survives it. `_extract` is therefore
    asked directly.
    """
    from korpus.application.risk import RiskThresholds

    from apps.api.tests.test_intra_span_contradiction import _evidence

    evidence = _evidence(BODY)
    service = DriftingService.__new__(DriftingService)
    service.answer_policy = AnswerPolicy(
        minimum_score=0.0,
        minimum_query_coverage=0.0,
        minimum_support_score=0.9,
        calibration_id="test",
    )

    claims, citations, _covered = service._extract(
        [evidence],
        frozenset({"журнал"}),
        RiskThresholds(
            minimum_score=0.0,
            minimum_query_coverage=0.0,
            minimum_support_score=0.9,
            minimum_authority=0.0,
        ),
    )

    assert claims == []
    assert citations == []


def test_the_extraction_step_keeps_an_exact_extract() -> None:
    """The negative control: the same gate must not reject a verbatim quote."""
    from korpus.application.risk import RiskThresholds

    from apps.api.tests.test_intra_span_contradiction import _evidence

    evidence = _evidence(BODY)
    service = ExtractiveAnswerService.__new__(ExtractiveAnswerService)
    service.answer_policy = AnswerPolicy(
        minimum_score=0.0,
        minimum_query_coverage=0.0,
        minimum_support_score=0.9,
        calibration_id="test",
    )

    claims, citations, _covered = service._extract(
        [evidence],
        frozenset({"журнал"}),
        RiskThresholds(
            minimum_score=0.0,
            minimum_query_coverage=0.0,
            minimum_support_score=0.9,
            minimum_authority=0.0,
        ),
    )

    assert len(claims) == 1
    assert claims[0].support_score == 1.0
    assert len(citations) == 1


def test_a_claim_that_drifts_from_its_span_is_dropped(client: TestClient) -> None:
    result = ingest_text(client, text=BODY)
    approve(client, result["version"]["id"])
    real = get_answer_service(
        client.app.state.repository,
        PolicyEngine(),
        client.app.dependency_overrides[get_settings](),
        client.app.state.query_cache,
        client.app.state.semantic_source,
    )
    policy = AnswerPolicy(
        minimum_score=real.answer_policy.minimum_score,
        minimum_query_coverage=real.answer_policy.minimum_query_coverage,
        # The gate is what is under test, so it is set where a drifting claim fails it
        # and an exact extract still passes.
        minimum_support_score=0.9,
        calibration_id=real.answer_policy.calibration_id,
    )
    service = DriftingService(
        client.app.state.repository, real.retriever, PolicyEngine(), policy
    )
    client.app.dependency_overrides[get_answer_service] = lambda: service

    answer = client.post("/v1/answers", json={"text": f"як ведеться журнал {MARKER}"}).json()

    assert answer["status"] != "answered", answer
    assert answer["citations"] == []
