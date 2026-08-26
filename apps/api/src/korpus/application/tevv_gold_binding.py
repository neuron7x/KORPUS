"""Bind a passing gold-annotation receipt to the exact production TEVV system."""

from __future__ import annotations

import hashlib
from typing import Any


def evaluate_gold_receipt_binding(
    evidence: dict[str, Any],
    receipt: dict[str, Any],
    receipt_bytes: bytes,
    *,
    required: bool,
    source: str,
    release: str,
) -> dict[str, bool]:
    bindings = receipt.get("bindings", {}) if isinstance(receipt, dict) else {}
    corpus = evidence.get("corpus", {})
    identity_matches = (
        bindings.get("source_tree_sha256") == source
        and bindings.get("release") == release
        and bindings.get("corpus_release_sha256") == corpus.get("document_set_sha256")
        and bindings.get("model_id") == evidence.get("model_id")
        and bindings.get("configuration_sha256") == evidence.get("configuration_sha256")
    )
    return {
        "gold_receipt_present": not required or bool(receipt_bytes),
        "gold_receipt_pass": not required
        or (
            receipt.get("schema") == "korpus.gold-annotation-admission.v1"
            and receipt.get("status") == "PASS"
        ),
        "gold_receipt_digest_bound": not required
        or evidence.get("gold_annotation_receipt_sha256")
        == hashlib.sha256(receipt_bytes).hexdigest(),
        "gold_receipt_system_bound": not required or identity_matches,
    }
