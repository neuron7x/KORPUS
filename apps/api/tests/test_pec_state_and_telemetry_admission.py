"""Counter admission in the evidence state, and the label collapse in PEC telemetry.

`build_evidence_state` turns a retrieval result into the feature vector a controller reads,
and every count in it has to be a real non-negative integer: `True` is an `int` in Python,
so a boolean budget field would be admitted as 1 and change a promotion decision.

`_fallback_label` maps a refusal reason onto a metric label. The support-bound family is
collapsed on purpose — the reasons carry a numeric suffix, and an unbounded label set is a
cardinality explosion in the metrics backend rather than a useful signal.
"""

from __future__ import annotations

import pytest
from korpus.application.evidence_state import FEATURE_NAMES, build_evidence_state
from korpus.application.risk_rules import QueryRisk
from korpus.infrastructure.pec_observability import _fallback_label


def _state(**changes: object) -> object:
    values: dict[str, object] = {
        "query": "чи обов'язкове ведення журналу",
        "risk": QueryRisk.STANDARD,
        "evidence": [],
        "eligible_evidence_count": 0,
        "sparse_dense_overlap": 0.0,
        "semantic_available": False,
        "budget_state": None,
    }
    values.update(changes)
    return build_evidence_state(**values)  # type: ignore[arg-type]


def test_a_well_formed_state_is_built() -> None:
    """The dual: every refusal below is vacuous if nothing can be built at all."""
    state = _state()
    assert state.eligible_evidence_count == 0  # type: ignore[attr-defined]


@pytest.mark.parametrize("count", [-1, 1.5, "3", None, float("nan")])
def test_an_eligible_count_that_is_not_a_non_negative_integer_is_refused(
    count: object,
) -> None:
    """The count is a denominator downstream; a float or a string makes it meaningless."""
    with pytest.raises(ValueError, match="eligible_evidence_count"):
        _state(eligible_evidence_count=count)


@pytest.mark.parametrize("key", ["cycles_used", "evidence_items", "conflicts"])
@pytest.mark.parametrize("value", [-1, 2.5, "1", None])
def test_a_budget_field_that_is_not_a_non_negative_integer_is_refused(
    key: str, value: object
) -> None:
    """Budget fields bound how much work a query may consume before it must abstain.

    A float admitted here spends a fractional cycle; a negative value grants unlimited
    ones, because every later comparison against the budget reads as under-spent.
    """
    with pytest.raises(ValueError, match=f"budget_state\\[{key}\\]"):
        _state(budget_state={key: value})


def test_a_boolean_is_not_a_count() -> None:
    """`True` passes `isinstance(x, int)`; the contract these fields use does not admit it.

    Without the strict check a budget of `True` reads as one cycle used and a budget of
    `False` as zero — both plausible numbers produced by a field that was never a number.
    """
    with pytest.raises(ValueError, match="budget_state"):
        _state(budget_state={"cycles_used": True})
    with pytest.raises(ValueError, match="eligible_evidence_count"):
        _state(eligible_evidence_count=True)


def test_an_unknown_feature_name_is_a_key_error_rather_than_a_default() -> None:
    """The controller reads features by name; a silent default would train on a constant."""
    state = _state()
    for name in FEATURE_NAMES:
        state.feature_value(name)  # type: ignore[attr-defined]
    with pytest.raises(KeyError, match="unknown PEC feature"):
        state.feature_value("invented_later")  # type: ignore[attr-defined]


def test_no_reason_labels_as_none_rather_than_as_empty() -> None:
    """An empty label and an absent one are different rows in a metrics backend."""
    assert _fallback_label(None) == "none"


@pytest.mark.parametrize(
    "reason",
    [
        "state_below_support:0.42",
        "state_above_support:1.98",
        "unsupported_non_numeric_feature:authority_class",
    ],
)
def test_the_support_bound_family_collapses_to_one_label(reason: str) -> None:
    """These reasons carry a numeric or field suffix, so each one is a distinct string.

    Passing them through unchanged makes the label set unbounded — one series per
    threshold value observed — which is the cardinality failure that takes a metrics
    backend down rather than a signal anybody can read.
    """
    assert _fallback_label(reason) == "support_bound"


def test_an_unrecognised_reason_collapses_to_other() -> None:
    """The same bound applies to reasons that are not in the known set at all."""
    assert _fallback_label("something_new_from_a_later_release") == "other"
    assert _fallback_label("") == "other"
