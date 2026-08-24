"""Emergency access that costs something to use, and cannot be used quietly.

IAM-008. There was no path for "the reviewer with the clearance is unreachable and a
soldier needs the order now", which means the real path was somebody's admin token and no
record that it happened. A break-glass control that does not exist is not absent — it is
informal, and informal is the state where nobody can say afterwards who saw what.

The tests are written as attempts to abuse it, because that is the only interesting
question about an emergency path. One person cannot elevate themselves. An approver
cannot grant a clearance above their own. A grant expires. And it never carries approval
authority — an emergency is a reason to read something, and a document approved under
duress by someone the reviewer registry does not know is exactly what the registry exists
to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from korpus.application.break_glass import (
    MAX_GRANT_MINUTES,
    BreakGlassRefused,
    grant,
)
from korpus.domain.models import AccessTier, Identity

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
REASON = "втрачено зв'язок з черговим офіцером, потрібен наказ про евакуацію"


def _identity(subject: str, roles: set[str], clearance: AccessTier) -> Identity:
    return Identity(
        subject=subject,
        roles=frozenset(roles),
        clearance=clearance,
        corpora=frozenset({"public"}),
    )


REQUESTER = _identity("soldier", {"user"}, AccessTier.PUBLIC)
APPROVER = _identity("duty-officer", {"admin"}, AccessTier.RESTRICTED)


def _grant(**overrides: object):
    arguments = {
        "requester": REQUESTER,
        "approver": APPROVER,
        "reason": REASON,
        "clearance": AccessTier.RESTRICTED,
        "corpora": frozenset({"restricted-demo"}),
        "now": NOW,
    }
    arguments.update(overrides)
    return grant(**arguments)  # type: ignore[arg-type]


def test_a_grant_widens_reach_and_records_both_names() -> None:
    issued = _grant()

    elevated = issued.elevate(REQUESTER, NOW)
    assert elevated.clearance == AccessTier.RESTRICTED
    assert "restricted-demo" in elevated.corpora
    record = issued.as_audit_record()
    assert record["requester"] == "soldier"
    assert record["approver"] == "duty-officer"
    assert REASON in str(record["reason"])


def test_one_person_cannot_break_glass_alone() -> None:
    """The property the whole control exists for."""
    with pytest.raises(BreakGlassRefused, match="one person twice"):
        _grant(requester=APPROVER)


def test_an_approver_cannot_grant_above_their_own_clearance() -> None:
    """Otherwise the approval is a stamp on something the approver could not read."""
    limited = _identity("junior", {"admin"}, AccessTier.REVIEWED)

    with pytest.raises(BreakGlassRefused, match="above their own"):
        _grant(approver=limited)


def test_someone_without_authority_cannot_approve() -> None:
    with pytest.raises(BreakGlassRefused, match="no authority"):
        _grant(approver=_identity("other-soldier", {"user"}, AccessTier.RESTRICTED))


def test_a_grant_never_carries_approval_authority() -> None:
    """An emergency is a reason to read. A document approved under duress is the failure."""
    with pytest.raises(BreakGlassRefused, match="approval authority"):
        _grant(requester=_identity("curator", {"user", "reviewer"}, AccessTier.PUBLIC))


def test_roles_are_not_widened_by_an_elevation() -> None:
    issued = _grant()

    elevated = issued.elevate(REQUESTER, NOW)

    assert elevated.roles == REQUESTER.roles


def test_a_grant_expires() -> None:
    issued = _grant(minutes=30)

    assert issued.active_at(NOW + timedelta(minutes=29)) is True
    assert issued.active_at(NOW + timedelta(minutes=31)) is False
    with pytest.raises(BreakGlassRefused, match="expired"):
        issued.elevate(REQUESTER, NOW + timedelta(minutes=31))


def test_a_grant_cannot_outlast_the_ceiling() -> None:
    """An emergency that lasts a week is an entitlement nobody reviewed."""
    with pytest.raises(BreakGlassRefused, match="expire within"):
        _grant(minutes=MAX_GRANT_MINUTES + 1)


def test_a_grant_belongs_to_the_subject_it_was_issued_to() -> None:
    issued = _grant()
    somebody_else = _identity("passer-by", {"user"}, AccessTier.PUBLIC)

    with pytest.raises(BreakGlassRefused, match="nobody else"):
        issued.elevate(somebody_else, NOW)


@pytest.mark.parametrize("reason", ["", "терміново", "   ", "asap"])
def test_a_formality_is_not_a_reason(reason: str) -> None:
    """An investigator reads this first, and "urgent" tells them nothing."""
    with pytest.raises(BreakGlassRefused, match="not a reason"):
        _grant(reason=reason)


def test_a_grant_that_widens_nothing_is_refused() -> None:
    """A record of nothing is a record that teaches the control is free to use."""
    with pytest.raises(BreakGlassRefused, match="widens nothing"):
        _grant(corpora=frozenset())
