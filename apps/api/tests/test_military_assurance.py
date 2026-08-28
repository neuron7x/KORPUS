from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from korpus.application.military_assurance import (
    AudienceLevel,
    CorrectionKind,
    CorrectionSubmission,
    EvidenceClaim,
    ExplanationEnvelope,
    OfflinePackState,
    build_review_queue,
    presentation_equivalent,
    verify_offline_pack,
)
from korpus.application.offline_pack import canonical_json
from korpus.infrastructure.offline_pack_signer import Ed25519OfflinePackSigner


def make_pack(now: datetime):
    signer = Ed25519OfflinePackSigner("k", Ed25519PrivateKey.generate())
    payload = {
        "schema": "korpus.offline-pack.v1",
        "algorithm": "Ed25519",
        "key_id": "k",
        "subject": "s",
        "clearance": 0,
        "compartments": [],
        "corpora": ["public"],
        "policy_decision_id": "pd1:x",
        "corpus_release": "rel1",
        "issued_at": now.isoformat(),
        "valid_until": (now + timedelta(hours=1)).isoformat(),
        "revoked": False,
        "spans": [],
    }
    digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    signed = {**payload, "payload_sha256": digest}
    pack = {**signed, "signature": signer.sign_b64(canonical_json(signed).encode())}
    return pack, signer


def test_offline_verifier_accepts_only_signed_fresh_pack():
    now = datetime(2026, 8, 20, 12, tzinfo=UTC)
    pack, signer = make_pack(now)
    result = verify_offline_pack(pack, trusted_public_key_b64=signer.public_key_b64, now=now)
    assert result.state is OfflinePackState.VALID and result.usable

    tampered = dict(pack)
    tampered["corpus_release"] = "evil"
    assert (
        verify_offline_pack(tampered, trusted_public_key_b64=signer.public_key_b64, now=now).state
        is OfflinePackState.DIGEST_MISMATCH
    )
    assert (
        verify_offline_pack(
            pack, trusted_public_key_b64=signer.public_key_b64, now=now + timedelta(hours=2)
        ).state
        is OfflinePackState.EXPIRED
    )


def test_audience_adaptation_cannot_change_claim_or_evidence_identity():
    claims = (EvidenceClaim(id="c1", source_binding_ids=frozenset({"b1"})),)
    a = ExplanationEnvelope(audience=AudienceLevel.RECRUIT, claims=claims, explanation="Просто")
    b = ExplanationEnvelope(
        audience=AudienceLevel.INSTRUCTOR, claims=claims, explanation="Докладно"
    )
    assert presentation_equivalent(a, b)
    c = ExplanationEnvelope(
        audience=AudienceLevel.INSTRUCTOR,
        claims=(EvidenceClaim(id="c1", source_binding_ids=frozenset({"b2"})),),
        explanation="Інше",
    )
    assert not presentation_equivalent(a, c)


def test_corrections_deduplicate_but_never_mutate_truth():
    base = dict(
        kind=CorrectionKind.STALE_SOURCE,
        document_id="d",
        version_id="v",
        span_id="s",
        note="Є нова редакція",
    )
    queue = build_review_queue(
        [
            CorrectionSubmission(reporter_subject="u2", **base),
            CorrectionSubmission(reporter_subject="u1", **base),
        ]
    )
    assert len(queue) == 1
    assert queue[0].report_count == 2
    assert queue[0].reporter_subjects == ("u1", "u2")
    assert queue[0].state.value == "open"


def test_a_pack_of_an_unsupported_schema_is_refused_before_anything_else() -> None:
    """The schema decides how every other field is read; an unknown one is unreadable.

    Checking it first also means a future version cannot be partially interpreted by this
    code — which is the failure mode where an offline device trusts fields that moved.
    """
    now = datetime(2026, 8, 20, 12, tzinfo=UTC)
    pack, signer = make_pack(now)
    for schema in ("korpus.offline-pack.v2", "", None, 1):
        result = verify_offline_pack(
            {**pack, "schema": schema}, trusted_public_key_b64=signer.public_key_b64, now=now
        )
        assert result.state is OfflinePackState.SCHEMA_UNSUPPORTED
        assert result.usable is False


def test_a_revoked_pack_is_refused_even_though_its_signature_still_verifies() -> None:
    """Revocation outranks a valid signature: the pack was correct and is now withdrawn.

    An offline device has no other way to learn that an entitlement was cancelled, so the
    flag has to win over every integrity check that would otherwise pass.
    """
    now = datetime(2026, 8, 20, 12, tzinfo=UTC)
    pack, signer = make_pack(now)
    revoked = {**pack, "revoked": True}
    result = verify_offline_pack(
        revoked, trusted_public_key_b64=signer.public_key_b64, now=now
    )
    assert result.state is OfflinePackState.REVOKED
    assert result.usable is False


def test_a_pack_without_a_signature_or_digest_is_refused_rather_than_read() -> None:
    """Both fields must be strings before any cryptography runs on them."""
    now = datetime(2026, 8, 20, 12, tzinfo=UTC)
    pack, signer = make_pack(now)
    for missing in ("signature", "payload_sha256"):
        for value in (None, 42, [], {}):
            result = verify_offline_pack(
                {**pack, missing: value},
                trusted_public_key_b64=signer.public_key_b64,
                now=now,
            )
            assert result.state is OfflinePackState.DIGEST_MISMATCH
            assert result.usable is False


def test_a_pack_from_the_future_is_not_yet_valid_rather_than_valid() -> None:
    """A device whose clock is behind must not open a pack that has not started.

    Both ends of the window are checked, and they report differently: expired says the
    entitlement ended, not-yet-valid says this device is early — an operator can act on
    the difference.
    """
    now = datetime(2026, 8, 20, 12, tzinfo=UTC)
    pack, signer = make_pack(now)
    early = verify_offline_pack(
        pack, trusted_public_key_b64=signer.public_key_b64, now=now - timedelta(hours=2)
    )
    assert early.state is OfflinePackState.NOT_YET_VALID
    assert early.usable is False

    at_issue = verify_offline_pack(
        pack, trusted_public_key_b64=signer.public_key_b64, now=now
    )
    assert at_issue.state is OfflinePackState.VALID


def test_explanation_claim_ids_must_be_unique() -> None:
    """Claims are cited by id; two claims under one id make a citation ambiguous.

    `presentation_equivalent` compares envelopes by their claim set, so a duplicate id
    would let two envelopes with different evidence compare as the same explanation
    rendered for a different audience.
    """
    import pytest

    claim = EvidenceClaim(id="c1", source_binding_ids=frozenset({"b1"}))
    with pytest.raises(ValueError, match="claim ids must be unique"):
        ExplanationEnvelope(
            audience=AudienceLevel.OPERATOR,
            claims=(claim, claim),
            explanation="Пояснення",
        )

    ExplanationEnvelope(
        audience=AudienceLevel.OPERATOR,
        claims=(claim, EvidenceClaim(id="c2", source_binding_ids=frozenset({"b2"}))),
        explanation="Пояснення",
    )
