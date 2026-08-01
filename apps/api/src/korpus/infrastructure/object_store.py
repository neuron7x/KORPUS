from __future__ import annotations

import base64
import hashlib
import os
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
KEY_PATTERN = re.compile(r"^[a-f0-9]{2}/[a-f0-9]{2}/[a-f0-9]{64}$")
BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
DEFAULT_MAX_OBJECT_BYTES = 50 * 1024 * 1024


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class LocalObjectStore:
    """Atomic, content-addressed local object store with durable directory updates."""

    def __init__(self, root: Path, *, max_object_bytes: int = DEFAULT_MAX_OBJECT_BYTES) -> None:
        if max_object_bytes < 1:
            raise ValueError("max_object_bytes must be positive")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.max_object_bytes = max_object_bytes

    def put(self, content: bytes, source_hash: str, filename: str) -> str:
        del filename
        if not HASH_PATTERN.fullmatch(source_hash):
            raise ValueError("invalid source hash")
        if hashlib.sha256(content).hexdigest() != source_hash:
            raise ValueError("source hash does not match content")
        key = f"{source_hash[:2]}/{source_hash[2:4]}/{source_hash}"
        destination = self._resolve(key)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(destination.parent, 0o700)
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != source_hash:
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
            _fsync_directory(destination.parent)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return key

    def get(self, object_key: str) -> bytes:
        path = self._resolve(object_key)
        if path.stat().st_size > self.max_object_bytes:
            raise RuntimeError("local object exceeds configured read limit")
        content = path.read_bytes()
        expected = object_key.rsplit("/", 1)[-1]
        if hashlib.sha256(content).hexdigest() != expected:
            raise RuntimeError("local object integrity verification failed")
        return content

    def exists(self, object_key: str) -> bool:
        return self._resolve(object_key).is_file()

    def healthcheck(self) -> bool:
        try:
            fd, name = tempfile.mkstemp(prefix=".health-", dir=self.root)
            os.close(fd)
            os.unlink(name)
            return True
        except OSError:
            return False

    def close(self) -> None:
        return None

    def _resolve(self, object_key: str) -> Path:
        if not KEY_PATTERN.fullmatch(object_key):
            raise ValueError("invalid object key")
        path = (self.root / object_key).resolve()
        if self.root not in path.parents:
            raise ValueError("object key escapes store root")
        return path


class S3ObjectStore:
    """S3-compatible content-addressed store with bounded retries and checksum verification."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "objects",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        governance_retention_days: int = 0,
        force_path_style: bool = False,
        connect_timeout_seconds: float = 3.0,
        read_timeout_seconds: float = 15.0,
        max_attempts: int = 4,
        max_object_bytes: int = DEFAULT_MAX_OBJECT_BYTES,
        client: Any | None = None,
    ) -> None:
        normalized_prefix = prefix.strip("/")
        if (
            not BUCKET_PATTERN.fullmatch(bucket)
            or governance_retention_days < 0
            or max_object_bytes < 1
            or (normalized_prefix and (not PREFIX_PATTERN.fullmatch(normalized_prefix) or ".." in normalized_prefix.split("/")))
        ):
            raise ValueError("invalid S3 object store configuration")
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.prefix = normalized_prefix
        self.governance_retention_days = governance_retention_days
        self.max_object_bytes = max_object_bytes
        self.client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            config=Config(
                connect_timeout=connect_timeout_seconds,
                read_timeout=read_timeout_seconds,
                retries={"mode": "standard", "max_attempts": max_attempts},
                s3={"addressing_style": "path" if force_path_style else "auto"},
            ),
        )

    def _key(self, source_hash: str) -> str:
        if not HASH_PATTERN.fullmatch(source_hash):
            raise ValueError("invalid source hash")
        relative = f"{source_hash[:2]}/{source_hash[2:4]}/{source_hash}"
        return f"{self.prefix}/{relative}" if self.prefix else relative

    def _validate_key(self, object_key: str) -> str:
        prefix = f"{self.prefix}/" if self.prefix else ""
        if prefix and not object_key.startswith(prefix):
            raise ValueError("object key is outside configured prefix")
        relative = object_key[len(prefix) :]
        if not KEY_PATTERN.fullmatch(relative):
            raise ValueError("invalid object key")
        return relative.rsplit("/", 1)[-1]

    @staticmethod
    def _error_code(exc: Exception) -> str:
        return str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))

    def _head(self, key: str) -> dict[str, Any] | None:
        try:
            try:
                return self.client.head_object(Bucket=self.bucket, Key=key, ChecksumMode="ENABLED")
            except TypeError:
                return self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if self._error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

    @staticmethod
    def _verify_head(head: dict[str, Any], source_hash: str, content_length: int | None = None) -> None:
        if head.get("Metadata", {}).get("sha256") != source_hash:
            raise RuntimeError("S3 object integrity metadata mismatch")
        encoded = head.get("ChecksumSHA256")
        if encoded and encoded != base64.b64encode(bytes.fromhex(source_hash)).decode("ascii"):
            raise RuntimeError("S3 checksum mismatch")
        if content_length is not None and "ContentLength" in head:
            if int(head["ContentLength"]) != content_length:
                raise RuntimeError("S3 content length mismatch")

    def put(self, content: bytes, source_hash: str, filename: str) -> str:
        del filename
        actual = hashlib.sha256(content).hexdigest()
        if actual != source_hash:
            raise ValueError("source hash does not match content")
        key = self._key(source_hash)
        head = self._head(key)
        if head is not None:
            self._verify_head(head, source_hash, len(content))
            return key
        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": content,
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(source_hash)).decode("ascii"),
            "Metadata": {"sha256": source_hash},
            "ContentType": "application/octet-stream",
            "ServerSideEncryption": "AES256",
        }
        if self.governance_retention_days:
            kwargs.update(
                ObjectLockMode="GOVERNANCE",
                ObjectLockRetainUntilDate=datetime.now(UTC)
                + timedelta(days=self.governance_retention_days),
            )
        self.client.put_object(**kwargs)
        written = self._head(key)
        if written is None:
            raise RuntimeError("S3 object missing after write")
        self._verify_head(written, source_hash, len(content))
        return key

    def get(self, object_key: str) -> bytes:
        source_hash = self._validate_key(object_key)
        response = self.client.get_object(Bucket=self.bucket, Key=object_key, ChecksumMode="ENABLED")
        declared = response.get("ContentLength")
        if declared is not None and int(declared) > self.max_object_bytes:
            close = getattr(response.get("Body"), "close", None)
            if callable(close):
                close()
            raise RuntimeError("S3 object exceeds configured read limit")
        body = response["Body"]
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                chunk = body.read(min(1024 * 1024, self.max_object_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_object_bytes:
                    raise RuntimeError("S3 object exceeds configured read limit")
                chunks.append(chunk)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        content = b"".join(chunks)
        expected = response.get("Metadata", {}).get("sha256")
        if expected != source_hash or hashlib.sha256(content).hexdigest() != source_hash:
            raise RuntimeError("S3 object integrity verification failed")
        encoded = response.get("ChecksumSHA256")
        if encoded and encoded != base64.b64encode(bytes.fromhex(source_hash)).decode("ascii"):
            raise RuntimeError("S3 response checksum mismatch")
        return content

    def exists(self, object_key: str) -> bool:
        self._validate_key(object_key)
        return self._head(object_key) is not None

    def healthcheck(self) -> bool:
        try:
            self.client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=f"{self.prefix}/" if self.prefix else "",
                MaxKeys=1,
            )
            if self.governance_retention_days:
                versioning = self.client.get_bucket_versioning(Bucket=self.bucket)
                if versioning.get("Status") != "Enabled":
                    return False
                lock = self.client.get_object_lock_configuration(Bucket=self.bucket)
                if lock.get("ObjectLockConfiguration", {}).get("ObjectLockEnabled") != "Enabled":
                    return False
            return True
        except Exception:
            return False

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
