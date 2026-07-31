from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class AnchorError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditAnchor:
    sequence: int
    head_hash: str


class FileAuditAnchorStore:
    """Separate tamper-evident checkpoint for detecting ledger truncation.

    Writes are monotonic and guarded by both a process lock and an OS file lock,
    preventing an older concurrent commit from regressing the anchor.
    """

    def __init__(self, path: Path, key: bytes) -> None:
        self.path = path
        self.key = key
        self._process_lock = threading.RLock()

    def _mac(self, sequence: int, head_hash: str) -> str:
        message = f"v1:{sequence}:{head_hash}".encode("ascii")
        return hmac.new(self.key, message, hashlib.sha256).hexdigest()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with self._process_lock, lock_path.open("a+b") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def write(self, sequence: int, head_hash: str) -> None:
        with self._locked():
            current = self._read_unlocked()
            if current.sequence > sequence:
                return
            if current.sequence == sequence:
                if current.head_hash != head_hash:
                    raise AnchorError("conflicting audit anchor at identical sequence")
                return
            payload = {
                "schema": 1,
                "sequence": sequence,
                "head_hash": head_hash,
                "mac": self._mac(sequence, head_hash),
            }
            fd, temporary_name = tempfile.mkstemp(prefix=".audit-anchor-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary_name, 0o600)
                os.replace(temporary_name, self.path)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)

    def read(self) -> AuditAnchor:
        with self._locked():
            return self._read_unlocked()

    def _read_unlocked(self) -> AuditAnchor:
        if not self.path.exists():
            return AuditAnchor(sequence=0, head_hash="0" * 64)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            sequence = int(payload["sequence"])
            head_hash = str(payload["head_hash"])
            supplied_mac = str(payload["mac"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AnchorError("audit anchor is unreadable") from exc
        if sequence < 0 or len(head_hash) != 64:
            raise AnchorError("audit anchor has invalid fields")
        expected = self._mac(sequence, head_hash)
        if not hmac.compare_digest(expected, supplied_mac):
            raise AnchorError("audit anchor MAC mismatch")
        return AuditAnchor(sequence=sequence, head_hash=head_hash)
