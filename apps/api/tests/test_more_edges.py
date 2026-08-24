from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from korpus.domain.models import AccessTier, DocumentRecord, Identity
from korpus.infrastructure.object_store import LocalObjectStore


def test_object_store_is_content_addressed_atomic_and_filename_independent(tmp_path: Path):
    store = LocalObjectStore(tmp_path)
    payload = b"payload"
    digest = hashlib.sha256(payload).hexdigest()
    first = store.put(payload, digest, "../unsafe.txt")
    second = store.put(payload, digest, "different-name.txt")
    assert first == second
    assert store.get(first) == payload
    assert store.exists(first)
    assert (tmp_path / first).stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="invalid object key"):
        store.get("../../etc/passwd")
    with pytest.raises(ValueError, match="does not match"):
        store.put(b"other", digest, "x.txt")


def test_access_tier_parse_and_document_decision(public_identity: Identity):
    assert AccessTier.parse("restricted") is AccessTier.RESTRICTED
    document = DocumentRecord(
        canonical_title="Restricted document",
        corpus_id="public",
        issuer="Issuer",
        jurisdiction="UA",
        document_type="order",
        access_tier=AccessTier.RESTRICTED,
        classification="restricted",
    )
    from korpus.application.policy import PolicyEngine

    policy = PolicyEngine()
    decision = policy.can_access_document(public_identity, document)
    assert decision.allowed is False

    tier_only = DocumentRecord(
        canonical_title="Tier-gated public-classification document",
        corpus_id="public",
        issuer="Issuer",
        jurisdiction="UA",
        document_type="order",
        access_tier=AccessTier.RESTRICTED,
        classification="public",
    )
    assert policy.can_access_document(public_identity, tier_only).allowed is False

    classification_only = DocumentRecord(
        canonical_title="Classification-gated document",
        corpus_id="public",
        issuer="Issuer",
        jurisdiction="UA",
        document_type="order",
        access_tier=AccessTier.PUBLIC,
        classification="restricted",
    )
    assert policy.can_access_document(public_identity, classification_only).allowed is False
