from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from korpus.infrastructure.gcs import GcsObjectStore, GcsPreconditionFailed


class MemoryGcs:
    def __init__(self, bucket: str = "korpus-objects") -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}
        self.retention = 2_592_000
        self.closed = False

    def upload_create_only(self, name: str, content: bytes) -> dict[str, Any]:
        if name in self.objects:
            raise GcsPreconditionFailed("exists")
        self.objects[name] = bytes(content)
        return {"name": name, "size": str(len(content)), "generation": "1"}

    def download(self, name: str) -> bytes:
        return self.objects[name]

    def metadata(self, name: str) -> dict[str, Any] | None:
        if name not in self.objects:
            return None
        return {"name": name, "size": str(len(self.objects[name])), "generation": "1"}

    def list_names(self, prefix: str, *, max_results: int | None = None) -> list[str]:
        names = sorted(name for name in self.objects if name.startswith(prefix))
        return names if max_results is None else names[:max_results]

    def bucket_metadata(self) -> dict[str, Any]:
        return {"name": self.bucket, "retentionPolicy": {"retentionPeriod": str(self.retention)}}

    def close(self) -> None:
        self.closed = True


CONTENT = b"controlled corpus object\n"
DIGEST = hashlib.sha256(CONTENT).hexdigest()


def store(gcs: MemoryGcs | None = None, **kwargs: Any) -> GcsObjectStore:
    backend = gcs or MemoryGcs()
    return GcsObjectStore(
        bucket=backend.bucket,
        prefix="objects",
        retention_seconds=2_592_000,
        gcs=backend,  # type: ignore[arg-type]
        **kwargs,
    )


def test_gcs_object_round_trip_is_content_addressed_and_create_only() -> None:
    backend = MemoryGcs()
    object_store = store(backend)
    key = object_store.put(CONTENT, DIGEST, "source.txt")
    assert key == f"objects/{DIGEST[:2]}/{DIGEST[2:4]}/{DIGEST}"
    assert object_store.get(key) == CONTENT
    assert object_store.put(CONTENT, DIGEST, "again.txt") == key
    assert len(backend.objects) == 1


def test_gcs_object_store_refuses_hash_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        store().put(b"tampered", DIGEST, "source.txt")


def test_gcs_object_store_detects_remote_tampering() -> None:
    backend = MemoryGcs()
    object_store = store(backend)
    key = object_store.put(CONTENT, DIGEST, "source.txt")
    backend.objects[key] = b"tampered"
    with pytest.raises(RuntimeError, match="integrity"):
        object_store.get(key)


def test_gcs_object_store_refuses_object_outside_prefix() -> None:
    with pytest.raises(ValueError, match="outside"):
        store().get(f"quarantine/{DIGEST[:2]}/{DIGEST[2:4]}/{DIGEST}")


def test_gcs_object_store_requires_bucket_retention_for_health() -> None:
    backend = MemoryGcs()
    backend.retention = 10
    assert not store(backend).healthcheck()


def test_gcs_put_path_checks_size_and_hash(tmp_path: Path) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(CONTENT)
    object_store = store(max_object_bytes=len(CONTENT))
    key = object_store.put_path(path, DIGEST, "source.bin")
    assert object_store.get(key) == CONTENT


def test_gcs_get_to_path_is_atomic_on_verified_content(tmp_path: Path) -> None:
    object_store = store()
    key = object_store.put(CONTENT, DIGEST, "source.txt")
    target = tmp_path / "out" / "source.txt"
    object_store.get_to_path(key, target)
    assert target.read_bytes() == CONTENT
