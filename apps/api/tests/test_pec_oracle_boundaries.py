"""The oracle's refusals and its two UNKNOWN verdicts.

`solve_oracle` is the counterfactual judge: given what each retrieval action actually
cost and whether its answer was admissible, it names the action that should have been
taken. Everything downstream — the controller's promotion decision, the ablation, the
sensitivity report — reads its verdict.

On 2026-08-28 the module measured 63.6% branch coverage. The covered half was the half
that decides; the uncovered half was every input the judge must refuse to judge, plus
both paths where it declines to name a winner. A judge that cannot say "I cannot decide"
still produces a decision, and nothing downstream can tell the two apart.
"""

from __future__ import annotations

import math

import pytest
from korpus.application.pec_replay import ReplayOutcome, dominates, solve_oracle
from korpus.application.predictive_evidence_control import RetrievalAction


def _row(
    action: RetrievalAction,
    *,
    query_id: str = "q1",
    latency: float = 10.0,
    searches: int = 1,
    planner: int = 0,
    semantic: int = 0,
    candidates: int = 8,
    tokens: int = 0,
    cost: int = 0,
    quality: bool = True,
    error: bool = False,
    auth: bool = True,
) -> ReplayOutcome:
    return ReplayOutcome(
        query_id=query_id,
        group_id="g1",
        action=action,
        state_fingerprint="a" * 64,
        features={},
        authorization_ok=auth,
        answer_error=error,
        quality_ok=quality,
        answer_status="answered",
        gold_hit=True,
        latency_ms=latency,
        search_count=searches,
        planner_calls=planner,
        semantic_calls=semantic,
        candidate_count=candidates,
        external_tokens=tokens,
        provider_cost_microunits=cost,
    )


def test_an_empty_campaign_is_refused_rather_than_judged() -> None:
    """No observations is not the same as no admissible action."""
    with pytest.raises(ValueError, match="at least one action outcome"):
        solve_oracle([])


def test_outcomes_from_two_queries_cannot_be_compared() -> None:
    """Resource vectors are only commensurable within one query's counterfactuals."""
    with pytest.raises(ValueError, match="one query"):
        solve_oracle(
            [
                _row(RetrievalAction.STOP_USE_CURRENT_EVIDENCE, query_id="q1"),
                _row(RetrievalAction.PLAN_QUERY_VARIANTS, query_id="q2"),
            ]
        )


def test_a_missing_stop_baseline_is_reported_as_unknown_not_as_a_choice() -> None:
    """Every verdict is relative to what the unmodified pipeline already did.

    Without the baseline row there is nothing to improve on, and naming a winner would
    assert that acting beat not acting — a comparison that was never made.
    """
    decision = solve_oracle(
        [
            _row(RetrievalAction.PLAN_QUERY_VARIANTS),
            _row(RetrievalAction.ENABLE_SEMANTIC_RETRIEVAL),
        ]
    )
    assert decision.status == "UNKNOWN"
    assert decision.reason == "missing_original_query_stop_baseline"
    assert decision.action is RetrievalAction.BASELINE
    assert decision.admissible_actions == ()


def test_when_nothing_is_admissible_the_verdict_is_abstain() -> None:
    """Abstention is an action the system can take; "no winner" is not."""
    decision = solve_oracle(
        [
            _row(RetrievalAction.STOP_USE_CURRENT_EVIDENCE, quality=False),
            _row(RetrievalAction.PLAN_QUERY_VARIANTS, error=True),
            _row(RetrievalAction.ENABLE_SEMANTIC_RETRIEVAL, auth=False),
        ]
    )
    assert decision.action is RetrievalAction.ABSTAIN
    assert decision.status == "PASS"
    assert decision.reason == "no_admissible_answer_action"
    assert decision.admissible_actions == ()


def test_incomparable_minima_are_reported_rather_than_broken_by_a_tiebreak() -> None:
    """Two actions, each cheaper on a different axis, have no ordering between them.

    Inventing one — a weighted sum, a preferred axis — would make the oracle's verdict a
    function of that weighting rather than of the observations, and the weighting would
    be nowhere in the evidence.
    """
    decision = solve_oracle(
        [
            _row(RetrievalAction.STOP_USE_CURRENT_EVIDENCE, quality=False),
            _row(RetrievalAction.PLAN_QUERY_VARIANTS, latency=5.0, tokens=100),
            _row(RetrievalAction.ENABLE_SEMANTIC_RETRIEVAL, latency=50.0, tokens=1),
        ]
    )
    assert decision.status == "UNKNOWN"
    assert decision.reason == "incomparable_pareto_minima"
    assert decision.action is RetrievalAction.BASELINE
    assert set(decision.admissible_actions) == {
        RetrievalAction.PLAN_QUERY_VARIANTS.value,
        RetrievalAction.ENABLE_SEMANTIC_RETRIEVAL.value,
    }


def test_actions_that_cost_exactly_the_same_resolve_to_the_canonical_order() -> None:
    """Identical cost is not incomparability; the cheapest intervention wins by rule."""
    decision = solve_oracle(
        [
            _row(RetrievalAction.STOP_USE_CURRENT_EVIDENCE, quality=False),
            _row(RetrievalAction.PLAN_AND_SEMANTIC),
            _row(RetrievalAction.PLAN_QUERY_VARIANTS),
        ]
    )
    assert decision.status == "PASS"
    assert decision.reason == "resource_equivalent_canonical_action"
    assert decision.action is RetrievalAction.PLAN_QUERY_VARIANTS


class _Vector:
    """A minimal outcome stand-in used to drive the vector validator directly."""

    def __init__(self, values: tuple[float, ...]) -> None:
        self._values = values

    def resources(self) -> tuple[float, ...]:
        return self._values

    def admissible(self) -> bool:
        return True


def test_an_empty_resource_vector_is_refused() -> None:
    """Dominance over zero dimensions is vacuously true for every pair."""
    with pytest.raises(ValueError, match="non-empty"):
        dominates(_Vector(()), _Vector(()))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "values", [(math.nan,), (math.inf,), (-math.inf,), (-1.0,), (1.0, -0.5)]
)
def test_a_resource_vector_that_is_not_finite_and_non_negative_is_refused(
    values: tuple[float, ...]
) -> None:
    """NaN makes `<=` false and `<` false at once, so a NaN row dominates nothing and is
    dominated by nothing — it would silently become an incomparable minimum."""
    with pytest.raises(ValueError, match="finite non-negative"):
        dominates(_Vector(values), _Vector(tuple(1.0 for _ in values)))  # type: ignore[arg-type]


def test_vectors_of_different_length_cannot_be_compared() -> None:
    """A row recorded before a resource axis was added is not comparable to one after."""
    with pytest.raises(ValueError, match="equal dimensionality"):
        dominates(_Vector((1.0, 2.0)), _Vector((1.0,)))  # type: ignore[arg-type]


class _Row(_Vector):
    """A campaign row with a resource vector of a chosen width."""

    def __init__(self, action: RetrievalAction, values: tuple[float, ...]) -> None:
        super().__init__(values)
        self.query_id = "q1"
        self.action = action


def test_the_oracle_rejects_a_campaign_whose_rows_disagree_on_dimensionality() -> None:
    """The same check at campaign level, before any pair is compared.

    A row recorded before an axis was added has a shorter vector. Comparing it pairwise
    would raise deep inside the dominance loop; the campaign-level check names the fault
    where it can still be attributed to the dataset.
    """
    with pytest.raises(ValueError, match="equal dimensionality"):
        solve_oracle(
            [
                _Row(RetrievalAction.STOP_USE_CURRENT_EVIDENCE, (1.0, 2.0, 3.0)),  # type: ignore[list-item]
                _Row(RetrievalAction.PLAN_QUERY_VARIANTS, (1.0,)),  # type: ignore[list-item]
            ]
        )
