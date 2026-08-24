"""Append-only audit anchoring backed by generation-conditional GCS objects."""
from __future__ import annotations

import json

from korpus.infrastructure.audit_anchor import AnchorError, AuditAnchor, _SignedAnchorCodec
from korpus.infrastructure.gcs import GcsJsonClient, GcsPreconditionFailed

class GcsAuditAnchorStore:
    """Append-only audit anchor over GCS create-only objects.

    A mutable `head.json` is incompatible with a locked bucket retention policy because
    replacing the object is itself a destructive mutation. Each sequence therefore gets
    exactly one object. `ifGenerationMatch=0` makes the first writer win atomically; a
    second writer at the same sequence must prove it wrote the identical hash.
    """

    def __init__(
        self,
        bucket: str,
        key: bytes,
        *,
        prefix: str = "audit/anchors",
        gcs: GcsJsonClient | None = None,
    ) -> None:
        normalized = prefix.strip("/")
        if not normalized or ".." in normalized.split("/"):
            raise ValueError("invalid GCS audit anchor prefix")
        self.bucket = bucket
        self.prefix = normalized
        self.codec = _SignedAnchorCodec(key)
        self.gcs = gcs or GcsJsonClient(bucket)

    def initialized(self) -> bool:
        return bool(self.gcs.list_names(f"{self.prefix}/", max_results=1))

    def write(self, sequence: int, head_hash: str) -> None:
        if sequence < 0 or sequence >= 10**32:
            raise AnchorError("audit anchor sequence is outside supported range")
        current = self.read()
        if current.sequence > sequence:
            return
        if current.sequence == sequence:
            if current.head_hash != head_hash:
                raise AnchorError("conflicting audit anchor at identical sequence")
            return
        name = self._name(sequence)
        payload = self.codec.encode(sequence, head_hash)
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            self.gcs.upload_create_only(name, body)
        except GcsPreconditionFailed:
            existing = self._read_name(name)
            if existing.sequence == sequence and existing.head_hash == head_hash:
                return
            raise AnchorError("GCS audit anchor rejected conflicting sequence")
        written = self._read_name(name)
        if written.sequence != sequence or written.head_hash != head_hash:
            raise AnchorError("GCS audit anchor failed post-write verification")

    def read(self) -> AuditAnchor:
        names = self.gcs.list_names(f"{self.prefix}/")
        if not names:
            return AuditAnchor(sequence=0, head_hash="0" * 64)
        parsed: list[tuple[int, str]] = []
        for name in names:
            sequence = self._sequence_from_name(name)
            parsed.append((sequence, name))
        sequence, name = max(parsed, key=lambda item: item[0])
        anchor = self._read_name(name)
        if anchor.sequence != sequence:
            raise AnchorError("GCS audit anchor name/payload sequence mismatch")
        return anchor

    def reset(self) -> None:
        raise AnchorError("GCS audit anchor reset is forbidden")

    def close(self) -> None:
        self.gcs.close()

    def _name(self, sequence: int) -> str:
        return f"{self.prefix}/{sequence:032d}.json"

    def _sequence_from_name(self, name: str) -> int:
        prefix = f"{self.prefix}/"
        if not name.startswith(prefix) or not name.endswith(".json"):
            raise AnchorError("GCS audit anchor inventory contains an invalid object name")
        digits = name[len(prefix):-5]
        if len(digits) != 32 or not digits.isdigit():
            raise AnchorError("GCS audit anchor inventory contains an invalid sequence")
        return int(digits)

    def _read_name(self, name: str) -> AuditAnchor:
        try:
            payload = json.loads(self.gcs.download(name).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AnchorError("GCS audit anchor is unreadable") from exc
        return self.codec.decode(payload)

