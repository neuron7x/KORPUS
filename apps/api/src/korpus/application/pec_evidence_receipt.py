from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def canonical_receipt(
    payload: Mapping[str, object], *, release: str, source_digest: str, collection_digest: str
) -> dict[str, object]:
    if str(payload.get("release", "")) != release:
        raise ValueError("receipt release mismatch")
    if str(payload.get("source_digest", "")) != source_digest:
        raise ValueError("receipt source digest mismatch")
    if str(payload.get("collection_digest", "")) != collection_digest:
        raise ValueError("receipt collection digest mismatch")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise ValueError("receipt artifacts are required")
    normalized = {str(k): str(v) for k, v in sorted(artifacts.items())}
    if any(
        len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value)
        for value in normalized.values()
    ):
        raise ValueError("artifact digests must be lowercase sha256")
    body = {
        "release": release,
        "source_digest": source_digest,
        "collection_digest": collection_digest,
        "artifacts": normalized,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**body, "receipt_sha256": digest}
