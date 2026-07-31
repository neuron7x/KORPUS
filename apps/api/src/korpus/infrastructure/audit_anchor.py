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
from typing import Any, Iterator, Protocol

import httpx


class AnchorError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditAnchor:
    sequence: int
    head_hash: str


class AuditAnchorStore(Protocol):
    def initialized(self) -> bool: ...

    def write(self, sequence: int, head_hash: str) -> None: ...

    def read(self) -> AuditAnchor: ...

    def reset(self) -> None: ...


class _SignedAnchorCodec:
    def __init__(self, key: bytes) -> None:
        self.key = key

    def mac(self, sequence: int, head_hash: str) -> str:
        message = f"v1:{sequence}:{head_hash}".encode("ascii")
        return hmac.new(self.key, message, hashlib.sha256).hexdigest()

    def encode(self, sequence: int, head_hash: str) -> dict[str, Any]:
        if sequence < 0 or len(head_hash) != 64:
            raise AnchorError("audit anchor has invalid fields")
        return {
            "schema": 1,
            "sequence": sequence,
            "head_hash": head_hash,
            "mac": self.mac(sequence, head_hash),
        }

    def decode(self, payload: Any) -> AuditAnchor:
        try:
            if int(payload["schema"]) != 1:
                raise ValueError("unsupported schema")
            sequence = int(payload["sequence"])
            head_hash = str(payload["head_hash"])
            supplied_mac = str(payload["mac"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AnchorError("audit anchor is unreadable") from exc
        if sequence < 0 or len(head_hash) != 64:
            raise AnchorError("audit anchor has invalid fields")
        expected = self.mac(sequence, head_hash)
        if not hmac.compare_digest(expected, supplied_mac):
            raise AnchorError("audit anchor MAC mismatch")
        return AuditAnchor(sequence=sequence, head_hash=head_hash)


class FileAuditAnchorStore:
    """Separate local checkpoint with monotonic, fsync-backed atomic writes."""

    def __init__(self, path: Path, key: bytes) -> None:
        self.path = path
        self.codec = _SignedAnchorCodec(key)
        self._process_lock = threading.RLock()

    def initialized(self) -> bool:
        return self.path.exists()

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
            payload = self.codec.encode(sequence, head_hash)
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
        except (OSError, json.JSONDecodeError) as exc:
            raise AnchorError("audit anchor is unreadable") from exc
        return self.codec.decode(payload)

    def reset(self) -> None:
        with self._locked():
            if self.path.exists():
                self.path.unlink()


class HttpAuditAnchorStore:
    """Remote monotonic anchor client.

    The remote endpoint must provide GET and conditional PUT semantics. PUT must
    reject sequence regression and conflicting hashes at an identical sequence
    with HTTP 409. The client additionally verifies the HMAC on every read.
    """

    def __init__(
        self,
        endpoint: str,
        key: bytes,
        *,
        token: str | None = None,
        timeout_seconds: float = 5.0,
        client: Any | None = None,
    ) -> None:
        if not endpoint.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("audit anchor endpoint must use HTTPS or loopback HTTP")
        self.endpoint = endpoint.rstrip("/")
        self.codec = _SignedAnchorCodec(key)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.client = client or httpx.Client(timeout=timeout_seconds, headers=headers)

    def initialized(self) -> bool:
        response = self.client.get(self.endpoint)
        if response.status_code == 404:
            return False
        self._raise_for_status(response)
        self.codec.decode(response.json())
        return True

    def write(self, sequence: int, head_hash: str) -> None:
        payload = self.codec.encode(sequence, head_hash)
        response = self.client.put(
            self.endpoint,
            json=payload,
            headers={"Idempotency-Key": f"audit-anchor-v1:{sequence}:{head_hash}"},
        )
        if response.status_code in {200, 201, 204}:
            return
        if response.status_code == 409:
            current = self.read()
            if current.sequence > sequence or (
                current.sequence == sequence and current.head_hash == head_hash
            ):
                return
            raise AnchorError("remote audit anchor rejected monotonic update")
        self._raise_for_status(response)

    def read(self) -> AuditAnchor:
        response = self.client.get(self.endpoint)
        if response.status_code == 404:
            return AuditAnchor(sequence=0, head_hash="0" * 64)
        self._raise_for_status(response)
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise AnchorError("remote audit anchor returned invalid JSON") from exc
        return self.codec.decode(payload)

    def reset(self) -> None:
        raise AnchorError("remote audit anchor reset is forbidden")

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        try:
            response.raise_for_status()
        except Exception as exc:
            status = getattr(response, "status_code", "UNKNOWN")
            raise AnchorError(f"remote audit anchor request failed: {status}") from exc
