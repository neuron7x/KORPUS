from __future__ import annotations

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
import hashlib


def make_pack(now: datetime):
    signer = Ed25519OfflinePackSigner("k", Ed25519PrivateKey.generate())
    payload = {
        "schema": "korpus.offline-pack.v1", "algorithm": "Ed25519", "key_id": "k",
        "subject": "s", "clearance": 0, "compartments": [], "corpora": ["public"],
        "policy_decision_id": "pd1:x", "corpus_release": "rel1",
        "issued_at": now.isoformat(), "valid_until": (now + timedelta(hours=1)).isoformat(),
        "revoked": False, "spans": [],
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

    tampered = dict(pack); tampered["corpus_release"] = "evil"
    assert verify_offline_pack(tampered, trusted_public_key_b64=signer.public_key_b64, now=now).state is OfflinePackState.DIGEST_MISMATCH
    assert verify_offline_pack(pack, trusted_public_key_b64=signer.public_key_b64, now=now + timedelta(hours=2)).state is OfflinePackState.EXPIRED


def test_audience_adaptation_cannot_change_claim_or_evidence_identity():
    claims = (EvidenceClaim(id="c1", source_binding_ids=frozenset({"b1"})),)
    a = ExplanationEnvelope(audience=AudienceLevel.RECRUIT, claims=claims, explanation="Просто")
    b = ExplanationEnvelope(audience=AudienceLevel.INSTRUCTOR, claims=claims, explanation="Докладно")
    assert presentation_equivalent(a, b)
    c = ExplanationEnvelope(audience=AudienceLevel.INSTRUCTOR, claims=(EvidenceClaim(id="c1", source_binding_ids=frozenset({"b2"})),), explanation="Інше")
    assert not presentation_equivalent(a, c)


def test_corrections_deduplicate_but_never_mutate_truth():
    base = dict(kind=CorrectionKind.STALE_SOURCE, document_id="d", version_id="v", span_id="s", note="Є нова редакція")
    queue = build_review_queue([
        CorrectionSubmission(reporter_subject="u2", **base),
        CorrectionSubmission(reporter_subject="u1", **base),
    ])
    assert len(queue) == 1
    assert queue[0].report_count == 2
    assert queue[0].reporter_subjects == ("u1", "u2")
    assert queue[0].state.value == "open"
