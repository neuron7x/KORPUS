import base64
import hashlib
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from korpus.application.military_assurance import OfflinePackState
from korpus.application.offline_pack import canonical_json
from korpus.application.offline_trust import (
    OfflineTrustStore,
    TrustedOfflineKey,
    verify_with_trust_store,
)


def _signed_pack(private: Ed25519PrivateKey, key_id: str, now: datetime):
    payload = {
        "schema": "korpus.offline-pack.v1",
        "algorithm": "Ed25519",
        "key_id": key_id,
        "corpus_release": "r1",
        "issued_at": now.isoformat(),
        "valid_until": (now + timedelta(hours=1)).isoformat(),
        "revoked": False,
        "spans": [],
    }
    digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    signed = {**payload, "payload_sha256": digest}
    signature = base64.b64encode(private.sign(canonical_json(signed).encode())).decode()
    return {**signed, "signature": signature}


def _key(private, key_id, start, end=None, revoked=None):
    raw = private.public_key().public_bytes_raw()
    return TrustedOfflineKey(
        key_id=key_id,
        public_key_b64=base64.b64encode(raw).decode(),
        valid_from=start,
        valid_until=end,
        revoked_at=revoked,
    )


def test_key_rotation_accepts_current_key_and_rejects_retired_key():
    now = datetime(2026, 8, 20, 12, tzinfo=UTC)
    old = Ed25519PrivateKey.generate()
    current = Ed25519PrivateKey.generate()
    store = OfflineTrustStore(
        keys=(
            _key(old, "old", now - timedelta(days=10), now - timedelta(days=1)),
            _key(current, "current", now - timedelta(days=1)),
        )
    )
    assert (
        verify_with_trust_store(_signed_pack(current, "current", now), store, now=now).state
        is OfflinePackState.VALID
    )
    assert (
        verify_with_trust_store(_signed_pack(old, "old", now), store, now=now).state
        is OfflinePackState.SIGNATURE_INVALID
    )


def test_revocation_is_fail_closed():
    now = datetime(2026, 8, 20, 12, tzinfo=UTC)
    key = Ed25519PrivateKey.generate()
    store = OfflineTrustStore(
        keys=(_key(key, "k1", now - timedelta(days=1), revoked=now - timedelta(minutes=1)),)
    )
    result = verify_with_trust_store(_signed_pack(key, "k1", now), store, now=now)
    assert not result.usable
