"""Replacing the audit key must not invalidate everything that happened before it.

AUD-003. Every event was signed with one key and verified with whatever key the process
held, so rotating it invalidated the entire history at once: the verifier recomputes each
HMAC, and with a new key none of them match. The only way to change the key was to stop
being able to prove anything that had happened — which means the key was never rotated,
which is the finding.

An event records the id of the key that signed it, verification uses the key the event
names, and rotation adds a key and makes it active while the previous ones stay able to
verify and unable to sign. That set of still-honoured keys is the dual-validation window:
not a period of time, but the property the window was for.

Revocation is not deletion, and the last test is why. A revoked key's events still verify
— the bytes did not change and the chain still links — and are reported as signed by
something no longer trusted. Deleting the key would turn "signed by something we no longer
trust" into "cannot be verified", and an investigator needs the first.
"""

from __future__ import annotations

import pytest
from korpus.application.keyring import LEGACY_KEY_ID, AuditKeyRing, KeyRingError
from korpus.application.policy import PolicyEngine
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.repository import SqlRepository

FIRST = b"first-key-material-0123456789abcdef"
SECOND = b"second-key-material-0123456789abcd"
MESSAGE = b"sequence=1|action=answer.completed"


def _rotated() -> AuditKeyRing:
    return AuditKeyRing(keys={"2026-08-a": FIRST, "2026-08-b": SECOND}, active_key_id="2026-08-b")


def test_events_signed_before_a_rotation_still_verify() -> None:
    """The whole point. A rotation that loses the history is not a rotation."""
    before = AuditKeyRing.single(FIRST, "2026-08-a")
    key_id, signature = before.sign(MESSAGE)

    assert _rotated().verify(key_id, MESSAGE, signature) is True


def test_the_new_key_signs_and_the_old_one_no_longer_can() -> None:
    ring = _rotated()

    key_id, signature = ring.sign(MESSAGE)

    assert key_id == "2026-08-b"
    assert ring.verify("2026-08-b", MESSAGE, signature) is True
    assert ring.verify("2026-08-a", MESSAGE, signature) is False


def test_an_event_naming_an_unknown_key_is_invalid() -> None:
    """Fail closed. A verifier that skips what it cannot check reports a hole as intact."""
    _, signature = _rotated().sign(MESSAGE)

    assert _rotated().verify("a-key-nobody-has", MESSAGE, signature) is False


def test_events_written_before_key_ids_existed_are_attributed_not_orphaned() -> None:
    """They were all signed with the one key the deployment held; naming it keeps them."""
    ring = AuditKeyRing(keys={LEGACY_KEY_ID: FIRST, "2026-08-b": SECOND}, active_key_id="2026-08-b")
    _, signature = AuditKeyRing.single(FIRST).sign(MESSAGE)

    assert ring.verify(LEGACY_KEY_ID, MESSAGE, signature) is True
    # An empty key id is the same event, read from a row written before the column.
    assert ring.verify("", MESSAGE, signature) is True


def test_a_revoked_key_still_verifies_and_is_reported_as_revoked() -> None:
    """ "Signed by something we no longer trust" and "cannot be verified" differ."""
    ring = AuditKeyRing(
        keys={"2026-08-a": FIRST, "2026-08-b": SECOND},
        active_key_id="2026-08-b",
        revoked=frozenset({"2026-08-a"}),
    )
    _, signature = AuditKeyRing.single(FIRST, "2026-08-a").sign(MESSAGE)

    assert ring.verify("2026-08-a", MESSAGE, signature) is True
    assert ring.is_revoked("2026-08-a") is True
    assert ring.is_revoked("2026-08-b") is False


def test_a_revoked_key_cannot_be_the_active_one() -> None:
    """Otherwise every new event is written under a key nobody trusts, silently."""
    with pytest.raises(KeyRingError, match="revoked"):
        AuditKeyRing(
            keys={"2026-08-a": FIRST},
            active_key_id="2026-08-a",
            revoked=frozenset({"2026-08-a"}),
        )


def test_an_active_key_outside_the_ring_is_refused() -> None:
    with pytest.raises(KeyRingError, match="not in the ring"):
        AuditKeyRing(keys={"2026-08-a": FIRST}, active_key_id="2026-08-b")


@pytest.mark.parametrize("candidate", ["", "has space", "Upper", "x" * 65, "semi;colon"])
def test_a_key_id_that_is_unsafe_in_a_row_or_a_command_is_refused(candidate: str) -> None:
    """It ends up in an audit row and in operator commands; both constrain it."""
    with pytest.raises(KeyRingError):
        AuditKeyRing(keys={candidate: FIRST}, active_key_id=candidate)


ACTOR = Identity(
    subject="rotation-drill",
    roles=frozenset({"admin", "auditor"}),
    clearance=AccessTier.RESTRICTED,
    corpora=frozenset({"public"}),
)


def _repository(path, ring: AuditKeyRing) -> SqlRepository:
    repository = SqlRepository(
        f"sqlite:///{path / 'rotation.db'}",
        # The legacy scalar still exists for the anchor store; the ring is what signs and
        # verifies events.
        "rotation-audit-key",
        PolicyEngine(),
        path / "anchor.json",
        audit_keyring=ring,
    )
    repository.initialize()
    return repository


def test_the_chain_written_under_one_key_verifies_after_rotating_to_another(tmp_path) -> None:
    """The drill, end to end through the database rather than over a ring in memory.

    Two events under key A, then the same database opened with a ring whose active key is
    B and whose A is verify-only. The chain must still verify: the reader has to use the
    key each *row* names, and a reader that used the active key would find every
    pre-rotation event forged.
    """
    first = AuditKeyRing(keys={"2026-08-a": FIRST}, active_key_id="2026-08-a")
    before = _repository(tmp_path, first)
    try:
        before.append_audit(ACTOR, "drill.one", "drill", "1", {"n": 1})
        before.append_audit(ACTOR, "drill.two", "drill", "2", {"n": 2})
        assert before.verify_audit().valid is True
    finally:
        before.close()

    after = _repository(tmp_path, _rotated())
    try:
        verification = after.verify_audit()
        assert verification.valid is True, verification
        assert verification.first_invalid_sequence is None

        # And the chain continues under the new key without a break.
        after.append_audit(ACTOR, "drill.three", "drill", "3", {"n": 3})
        assert after.verify_audit().valid is True
    finally:
        after.close()


def test_a_chain_opened_without_the_previous_key_does_not_verify(tmp_path) -> None:
    """The control. If it verified anyway, the key id would be decoration."""
    first = AuditKeyRing(keys={"2026-08-a": FIRST}, active_key_id="2026-08-a")
    before = _repository(tmp_path, first)
    try:
        before.append_audit(ACTOR, "drill.one", "drill", "1", {"n": 1})
    finally:
        before.close()

    orphaned = AuditKeyRing(keys={"2026-08-b": SECOND}, active_key_id="2026-08-b")
    after = _repository(tmp_path, orphaned)
    try:
        assert after.verify_audit().valid is False
    finally:
        after.close()
