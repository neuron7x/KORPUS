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


class S3ObjectStore:
    """S3-compatible content-addressed store with end-to-end SHA-256 checksums.

    The key is derived exclusively from content. A mismatching existing object is
    a hard collision. Optional governance retention can be enabled for buckets
    configured with Object Lock.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "objects",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        governance_retention_days: int = 0,
        client=None,
    ) -> None:
        if not bucket or governance_retention_days < 0:
            raise ValueError("invalid S3 object store configuration")
        import boto3

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.governance_retention_days = governance_retention_days
        self.client = client or boto3.client(
            "s3", endpoint_url=endpoint_url, region_name=region_name
        )

    def _key(self, source_hash: str) -> str:
        if not HASH_PATTERN.fullmatch(source_hash):
            raise ValueError("invalid source hash")
        relative = f"{source_hash[:2]}/{source_hash[2:4]}/{source_hash}"
        return f"{self.prefix}/{relative}" if self.prefix else relative

    def put(self, content: bytes, source_hash: str, filename: str) -> str:
        del filename
        import base64
        from datetime import UTC, datetime, timedelta

        actual = hashlib.sha256(content).hexdigest()
        if actual != source_hash:
            raise ValueError("source hash does not match content")
        key = self._key(source_hash)
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if str(error_code) not in {"404", "NoSuchKey", "NotFound"}:
                raise
        else:
            if head.get("Metadata", {}).get("sha256") != source_hash:
                raise RuntimeError("content-address collision")
            return key
        kwargs = {
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
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        if head.get("Metadata", {}).get("sha256") != source_hash:
            raise RuntimeError("S3 object integrity metadata missing after write")
        return key

    def get(self, object_key: str) -> bytes:
        if not object_key.startswith(f"{self.prefix}/" if self.prefix else ""):
            raise ValueError("object key is outside configured prefix")
        response = self.client.get_object(Bucket=self.bucket, Key=object_key, ChecksumMode="ENABLED")
        content = response["Body"].read()
        expected = response.get("Metadata", {}).get("sha256")
        if not expected or hashlib.sha256(content).hexdigest() != expected:
            raise RuntimeError("S3 object integrity verification failed")
        return content

    def exists(self, object_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=object_key)
            return True
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if str(code) in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
