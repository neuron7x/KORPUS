from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
KEY_PATTERN = re.compile(r"^[a-f0-9]{2}/[a-f0-9]{2}/[a-f0-9]{64}$")


class LocalObjectStore:
    """Atomic, content-addressed local object store.

    User filenames never participate in the storage path, eliminating traversal
    and ambiguous-name attacks. Raw source bytes are immutable after creation.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes, source_hash: str, filename: str) -> str:
        del filename
        if not HASH_PATTERN.fullmatch(source_hash):
            raise ValueError("invalid source hash")
        if hashlib.sha256(content).hexdigest() != source_hash:
            raise ValueError("source hash does not match content")
        key = f"{source_hash[:2]}/{source_hash[2:4]}/{source_hash}"
        destination = self._resolve(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != content:
                raise RuntimeError("content-address collision")
            return key
        fd, temporary_name = tempfile.mkstemp(prefix=".object-", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return key

    def get(self, object_key: str) -> bytes:
        return self._resolve(object_key).read_bytes()

    def exists(self, object_key: str) -> bool:
        return self._resolve(object_key).is_file()

    def _resolve(self, object_key: str) -> Path:
        if not KEY_PATTERN.fullmatch(object_key):
            raise ValueError("invalid object key")
        path = (self.root / object_key).resolve()
        if self.root not in path.parents:
            raise ValueError("object key escapes store root")
        return path
