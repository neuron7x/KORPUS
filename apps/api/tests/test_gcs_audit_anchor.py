from __future__ import annotations

import json
from typing import Any

import pytest

from korpus.infrastructure.audit_anchor import AnchorError
from korpus.infrastructure.gcs_audit_anchor import GcsAuditAnchorStore
from korpus.infrastructure.gcs import GcsPreconditionFailed


class MemoryGcs:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload_create_only(self, name: str, content: bytes) -> dict[str, Any]:
        if name in self.objects:
            raise GcsPreconditionFailed("exists")
        self.objects[name] = bytes(content)
        return {"name": name, "size": str(len(content)), "generation": "1"}

    def download(self, name: str) -> bytes:
        return self.objects[name]

    def list_names(self, prefix: str, *, max_results: int | None = None) -> list[str]:
        names = sorted(name for name in self.objects if name.startswith(prefix))
        return names if max_results is None else names[:max_results]

    def close(self) -> None:
        pass


def anchor(backend: MemoryGcs | None = None) -> tuple[GcsAuditAnchorStore, MemoryGcs]:
    gcs = backend or MemoryGcs()
    return GcsAuditAnchorStore("korpus-audit", b"a" * 40, gcs=gcs), gcs  # type: ignore[arg-type]


def test_gcs_anchor_is_append_only_and_monotonic() -> None:
    store, backend = anchor()
    assert store.read().sequence == 0
    store.write(1, "1" * 64)
    store.write(3, "3" * 64)
    store.write(2, "2" * 64)
    assert store.read().sequence == 3
    assert len(backend.objects) == 2
    assert all(name.endswith(".json") for name in backend.objects)


def test_gcs_anchor_same_sequence_is_idempotent_but_conflict_is_refused() -> None:
    store, _ = anchor()
    store.write(7, "7" * 64)
    store.write(7, "7" * 64)
    with pytest.raises(AnchorError, match="conflicting"):
        store.write(7, "8" * 64)


def test_gcs_anchor_detects_payload_tampering() -> None:
    store, backend = anchor()
    store.write(2, "2" * 64)
    name = next(iter(backend.objects))
    payload = json.loads(backend.objects[name])
    payload["head_hash"] = "f" * 64
    backend.objects[name] = json.dumps(payload).encode()
    with pytest.raises(AnchorError, match="MAC mismatch"):
        store.read()


def test_gcs_anchor_refuses_malformed_inventory_and_reset() -> None:
    store, backend = anchor()
    backend.objects["audit/anchors/not-a-sequence.json"] = b"{}"
    with pytest.raises(AnchorError, match="invalid sequence"):
        store.read()
    with pytest.raises(AnchorError, match="reset is forbidden"):
        store.reset()
