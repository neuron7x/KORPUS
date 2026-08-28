"""Every refusal in the replay row constructor, measured at 0% before this file.

`ReplayOutcome` is the typed boundary between a recorded decision and the counterfactual
oracle that later grades it. `test_pec_replay.py` builds well-formed rows and exercises
the oracle; the validator that decides what a well-formed row *is* had 11 uncovered
branches on 2026-08-28 — every one of them a raise.

An unvalidated replay row is worse than a missing one. `True` is an `int` in Python, so
a boolean slipped into a resource count passes an integer check; a NaN latency compares
false against every threshold, so a row carrying one is silently admissible under any
budget. The oracle would then rank a decision that never happened.
"""

from __future__ import annotations

import math

import pytest
from korpus.application.pec_replay import RESOURCE_FIELDS, ReplayOutcome
from korpus.application.predictive_evidence_control import RetrievalAction

WELL_FORMED: dict[str, object] = {
    "query_id": "q1",
    "group_id": "g1",
    "action": RetrievalAction.STOP_USE_CURRENT_EVIDENCE,
    "state_fingerprint": "a" * 64,
    "features": {},
    "authorization_ok": True,
    "answer_error": False,
    "quality_ok": True,
    "answer_status": "answered",
    "gold_hit": True,
    "latency_ms": 10.0,
    "search_count": 1,
    "planner_calls": 0,
    "semantic_calls": 0,
    "candidate_count": 8,
    "external_tokens": 0,
    "provider_cost_microunits": 0,
}


def _row(**changes: object) -> ReplayOutcome:
    return ReplayOutcome(**{**WELL_FORMED, **changes})  # type: ignore[arg-type]


def test_the_well_formed_row_is_admitted() -> None:
    """The positive control: without it, every assertion below could pass vacuously."""
    row = _row()
    assert row.admissible() is True
    assert row.resources() == (10.0, 1.0, 0.0, 0.0, 8.0, 0.0, 0.0)
    assert row.decision_signature() == ("answered", "")


@pytest.mark.parametrize("flag", ["authorization_ok", "answer_error", "quality_ok", "gold_hit"])
@pytest.mark.parametrize("truthy", [1, 0, "yes", None, 1.0])
def test_a_truthy_value_is_not_a_boolean_flag(flag: str, truthy: object) -> None:
    """`admissible()` reads these with `and`/`not`, where any truthy value would work.

    That is exactly why the type is checked at construction: `authorization_ok="no"`
    would read as authorized.
    """
    with pytest.raises(ValueError, match=flag):
        _row(**{flag: truthy})


@pytest.mark.parametrize("latency", [float("nan"), float("inf"), float("-inf"), -0.001, -50.0])
def test_a_latency_that_is_not_a_finite_non_negative_number_is_refused(latency: float) -> None:
    """NaN compares false against every bound, so it passes any budget it is tested against."""
    with pytest.raises(ValueError, match="latency_ms"):
        _row(latency_ms=latency)


@pytest.mark.parametrize("field_name", RESOURCE_FIELDS[1:])
@pytest.mark.parametrize("value", [-1, 1.5, float("nan"), "3", None])
def test_a_resource_count_must_be_a_non_negative_integer(field_name: str, value: object) -> None:
    """Costs are summed and compared; a float or a string makes the comparison meaningless."""
    with pytest.raises(ValueError, match=field_name):
        _row(**{field_name: value})


@pytest.mark.parametrize("name", ["", 0, None])
def test_a_quality_metric_needs_a_non_empty_string_name(name: object) -> None:
    """Metrics are keyed by name downstream; an unnamed one cannot be compared to itself."""
    with pytest.raises(ValueError, match="metric names"):
        _row(retrieval_quality={name: 1.0})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "1.0", None])
def test_a_quality_metric_value_must_be_finite(value: object) -> None:
    with pytest.raises(ValueError, match="retrieval_quality"):
        _row(retrieval_quality={"ndcg": value})


def test_a_finite_quality_metric_survives_including_a_negative_one() -> None:
    """Only finiteness is required: a metric may legitimately be negative or zero."""
    row = _row(retrieval_quality={"ndcg": 0.0, "delta": -0.25})
    assert math.isfinite(row.retrieval_quality["delta"])


@pytest.mark.parametrize("span", [("", 1), (None, 1)])
def test_a_retrieved_span_needs_an_identifier(span: tuple[object, int]) -> None:
    with pytest.raises(ValueError, match="span ids"):
        _row(retrieved_spans=(span,))


@pytest.mark.parametrize("rank", [0, -1, 1.5, "1", None])
def test_a_retrieved_span_rank_is_one_based(rank: object) -> None:
    """Rank 0 would make the top result indistinguishable from an unranked one."""
    with pytest.raises(ValueError, match="rank"):
        _row(retrieved_spans=(("span-1", rank),))


def test_a_well_formed_span_list_survives() -> None:
    row = _row(retrieved_spans=(("span-1", 1), ("span-2", 2)))
    assert row.retrieved_spans[1] == ("span-2", 2)
