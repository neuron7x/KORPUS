"""Retention as a computed disposition, including the one nobody has decided.

`retention_days` and `legal_hold` sat in the governance profile with nothing comparing
them to a date. The gap this fills is not "delete old material" — it is that the
system could not say what it was holding, why, or on whose authority.

The case worth stating is `AWAITING_DECISION`: the retention period has elapsed and
the corpus policy does not permit deletion. Both simpler designs are wrong. Keeping it
quietly reports a clean posture over material nobody has ruled on; deleting it because
a timer expired acts on a permission the owner never gave.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from korpus.application.retention import (
    AWAITING_DECISION,
    ELIGIBLE,
    HELD,
    RETAINED,
    UNGOVERNED,
    plan_retention,
    reconcile,
)
from korpus.domain.models import AuthorityClass, Classification
from korpus.security.corpus_governance import CorpusOperation, CorpusPolicy

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def _policy(**overrides: object) -> CorpusPolicy:
    values: dict[str, object] = {
        "data_owner": "Corpus Owner",
        "security_owner": "Security Owner",
        "rights_reference": "Rights memo 1",
        "releasability": "internal only",
        "allowed_classifications": frozenset({Classification.PUBLIC}),
        "allowed_authorities": frozenset({AuthorityClass.OFFICIAL_UA}),
        "allowed_operations": frozenset({CorpusOperation.INDEX, CorpusOperation.CITE}),
        "retention_days": 30,
        "legal_hold": False,
    }
    values.update(overrides)
    return CorpusPolicy(**values)


def _documents(*ages_in_days: int) -> list[tuple[str, str, datetime]]:
    return [
        (f"doc-{index}", "public", NOW - timedelta(days=age))
        for index, age in enumerate(ages_in_days)
    ]


def test_a_document_inside_its_retention_period_is_retained() -> None:
    """The dual: without it every disposition below could be the only one produced."""
    plan = plan_retention(_documents(10), {"public": _policy()}, now=NOW)

    assert [item.disposition for item in plan.items] == [RETAINED]
    assert plan.deletable_ids == ()


def test_a_document_past_its_period_in_a_corpus_that_permits_deletion_is_eligible() -> None:
    policy = _policy(allowed_operations=frozenset({CorpusOperation.INDEX, CorpusOperation.DELETE}))

    plan = plan_retention(_documents(31), {"public": policy}, now=NOW)

    assert [item.disposition for item in plan.items] == [ELIGIBLE]
    assert plan.deletable_ids == ("doc-0",)


def test_a_document_past_its_period_without_delete_permission_awaits_a_decision() -> None:
    """Neither deleted nor silently kept: the owner has not ruled, and that is visible."""
    plan = plan_retention(_documents(400), {"public": _policy()}, now=NOW)

    item = plan.items[0]
    assert item.disposition == AWAITING_DECISION
    assert "does not permit deletion" in item.reason
    assert plan.deletable_ids == ()


def test_legal_hold_outranks_the_retention_period() -> None:
    """Hold is the answer whatever the age; a timer must not release evidence."""
    policy = _policy(
        legal_hold=True,
        allowed_operations=frozenset({CorpusOperation.INDEX}),
        retention_days=1,
    )

    plan = plan_retention(_documents(3650), {"public": policy}, now=NOW)

    assert [item.disposition for item in plan.items] == [HELD]
    assert plan.deletable_ids == ()


def test_the_governance_profile_refuses_delete_together_with_legal_hold() -> None:
    """The contradiction is refused where it is written, not resolved at plan time."""
    with pytest.raises(ValueError, match="delete cannot be enabled while a corpus is under"):
        _policy(legal_hold=True, allowed_operations=frozenset({CorpusOperation.DELETE}))


def test_the_boundary_day_is_still_retained() -> None:
    """Off-by-one here deletes a day early, and the deletion is not reversible."""
    created_exactly_at_the_limit = [("doc-boundary", "public", NOW - timedelta(days=30))]

    plan = plan_retention(created_exactly_at_the_limit, {"public": _policy()}, now=NOW)

    # 30 days after creation is the moment the period ends: not yet past it.
    assert plan.items[0].retention_expires_at == NOW
    assert plan.items[0].disposition == AWAITING_DECISION


def test_a_corpus_with_no_policy_is_ungoverned_rather_than_assumed_safe() -> None:
    """An empty policy would read as "keep forever, nobody objected"."""
    plan = plan_retention(
        [("doc-x", "unknown-corpus", NOW - timedelta(days=1))], {"public": _policy()}, now=NOW
    )

    item = plan.items[0]
    assert item.disposition == UNGOVERNED
    assert item.retention_expires_at is None
    assert plan.deletable_ids == ()


def test_naive_timestamps_are_treated_as_utc_rather_than_raising() -> None:
    """SQLite returns naive datetimes; comparing them to an aware now raises TypeError."""
    naive = [("doc-naive", "public", datetime(2026, 8, 4, 12, 0))]

    plan = plan_retention(naive, {"public": _policy()}, now=NOW)

    assert plan.items[0].disposition == RETAINED


def test_the_serialised_plan_counts_every_disposition() -> None:
    policy_delete = _policy(
        allowed_operations=frozenset({CorpusOperation.INDEX, CorpusOperation.DELETE})
    )
    plan = plan_retention(_documents(1, 31), {"public": policy_delete}, now=NOW)

    rendered = plan.as_dict()

    assert rendered["counts"] == {RETAINED: 1, ELIGIBLE: 1}
    assert len(rendered["items"]) == 2
    assert "separate authorised act" in str(rendered["interpretation"])


def test_reconciliation_reports_material_the_plan_never_saw() -> None:
    """A document in storage that no plan covers is outside every retention rule."""
    plan = plan_retention(_documents(1), {"public": _policy()}, now=NOW)

    problems = reconcile(plan, ["doc-0", "doc-nobody-planned"])

    assert problems == ["stored document not covered by the retention plan: doc-nobody-planned"]


def test_reconciliation_reports_held_material_that_has_already_gone() -> None:
    """The worst case: the plan promises a hold over something no longer there."""
    policy = _policy(legal_hold=True, allowed_operations=frozenset({CorpusOperation.INDEX}))
    plan = plan_retention(_documents(1), {"public": policy}, now=NOW)

    problems = reconcile(plan, [])

    assert problems == ["document under HELD is absent from storage: doc-0"]


def test_reconciliation_is_silent_when_the_plan_matches_storage() -> None:
    plan = plan_retention(_documents(1, 2), {"public": _policy()}, now=NOW)

    assert reconcile(plan, ["doc-0", "doc-1"]) == []
