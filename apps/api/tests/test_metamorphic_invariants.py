"""The metamorphic rules: what a rephrasing of one question may never change.

A transformation rewrites a query and the pipeline answers it again. The rules state what
must hold across that pair — same authorization decision, risk class no weaker, evidence
authority no lower, gold evidence still retrievable, citations still source-bound, planner
permissions not wider. Measured on 2026-08-28 the module sat at 70.8% branch coverage with
every issue-detecting branch untaken: the rules were only ever exercised on pairs that
agreed.

A rule nothing has seen fire is a rule that can be deleted without a red build, and the
one it protects against is the cheapest attack on an evidence system — ask the same thing
in gentler words until the gate relaxes.
"""

from __future__ import annotations

import pytest
from korpus.application.pec_metamorphic_rules import metamorphic_issues

BASE: dict[str, object] = {
    "authorization_decision": "allow",
    "risk_rank": 2,
    "authority_rank": 3,
    "gold_retrievable": True,
    "answer_status": "answered",
}


def _transformed(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        **BASE,
        "semantics_validated": True,
        "citations_source_bound": True,
        "planner_permission_expanded": False,
    }
    payload.update(changes)
    return payload


def test_a_faithful_transformation_raises_nothing() -> None:
    """The dual: a rule set that fires on everything says nothing about anything."""
    assert metamorphic_issues(BASE, _transformed()) == []


def test_a_transformation_nobody_validated_is_reported() -> None:
    """Without semantic validation the pair is two questions, not one asked twice."""
    for value in (False, None, "yes", 1):
        assert "transformation_not_semantically_validated" in metamorphic_issues(
            BASE, _transformed(semantics_validated=value)
        )


def test_an_authorization_decision_that_changed_under_rephrasing_is_reported() -> None:
    """Access is a property of the asker, never of the wording."""
    assert "authorization_changed" in metamorphic_issues(
        BASE, _transformed(authorization_decision="deny")
    )


@pytest.mark.parametrize("rank", ["2", None, 2.0, True])
def test_a_risk_rank_that_is_not_a_strict_integer_is_reported(rank: object) -> None:
    """`True` is an `int` in Python, so a boolean would compare as rank 1 without this."""
    assert "invalid_risk_rank" in metamorphic_issues(BASE, _transformed(risk_rank=rank))
    assert "invalid_risk_rank" in metamorphic_issues({**BASE, "risk_rank": rank}, _transformed())


def test_a_rephrasing_that_lowers_the_risk_class_is_reported() -> None:
    """This is the attack the rule exists for: softer words, weaker classification."""
    assert "risk_class_weakened" in metamorphic_issues(BASE, _transformed(risk_rank=1))
    assert "risk_class_weakened" not in metamorphic_issues(BASE, _transformed(risk_rank=3))


@pytest.mark.parametrize("rank", ["3", None, 3.5, False])
def test_an_authority_rank_that_is_not_a_strict_integer_is_reported(rank: object) -> None:
    assert "invalid_authority_rank" in metamorphic_issues(
        BASE, _transformed(authority_rank=rank)
    )


def test_a_rephrasing_answered_from_weaker_evidence_is_reported() -> None:
    """Same question, lower-authority source, is a different answer wearing the same words."""
    assert "evidence_authority_degraded" in metamorphic_issues(
        BASE, _transformed(authority_rank=2)
    )


@pytest.mark.parametrize("value", ["true", None, 1, 0])
def test_a_gold_retrievable_flag_that_is_not_boolean_is_reported(value: object) -> None:
    assert "invalid_gold_retrievable" in metamorphic_issues(
        BASE, _transformed(gold_retrievable=value)
    )


def test_gold_evidence_that_stopped_being_retrievable_is_reported() -> None:
    """The known-correct span was reachable before the rewrite and is not after it."""
    assert "gold_evidence_lost" in metamorphic_issues(BASE, _transformed(gold_retrievable=False))
    assert "gold_evidence_lost" not in metamorphic_issues(
        {**BASE, "gold_retrievable": False}, _transformed(gold_retrievable=True)
    )


def test_citations_that_lost_their_source_binding_are_reported() -> None:
    for value in (False, None, "bound"):
        assert "citation_source_binding_failed" in metamorphic_issues(
            BASE, _transformed(citations_source_bound=value)
        )


@pytest.mark.parametrize("value", ["false", None, 0, 1])
def test_a_planner_permission_flag_that_is_not_boolean_is_reported(value: object) -> None:
    """An unreadable flag is treated as not-expanded and reported, never assumed safe."""
    issues = metamorphic_issues(BASE, _transformed(planner_permission_expanded=value))
    assert "invalid_planner_permission" in issues
    assert "planner_permission_expanded" not in issues


def test_a_rephrasing_that_widened_planner_permissions_is_reported() -> None:
    assert "planner_permission_expanded" in metamorphic_issues(
        BASE, _transformed(planner_permission_expanded=True)
    )


@pytest.mark.parametrize("status", ["insufficient_evidence", "requires_human_review"])
def test_a_permissive_rephrase_that_turned_an_abstention_into_an_answer_is_reported(
    status: str,
) -> None:
    """The composite rule, and the one that names the actual exploit.

    Abstaining before, answering after, and the only thing that changed is that the
    planner was allowed more. Each half is reported on its own; together they say the
    rewrite bought an answer with permission rather than with evidence.
    """
    issues = metamorphic_issues(
        {**BASE, "answer_status": status},
        _transformed(answer_status="answered", planner_permission_expanded=True),
    )
    assert "permissive_rephrase_changed_decision" in issues

    assert "permissive_rephrase_changed_decision" not in metamorphic_issues(
        {**BASE, "answer_status": status},
        _transformed(answer_status="answered", planner_permission_expanded=False),
    )
    assert "permissive_rephrase_changed_decision" not in metamorphic_issues(
        {**BASE, "answer_status": status},
        _transformed(answer_status=status, planner_permission_expanded=True),
    )
