from __future__ import annotations
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote
import httpx
from korpus.application.ports import ObjectStoreUnavailable
from korpus.infrastructure.gcp_identity import MetadataIdentityProvider, MetadataIdentityError
from korpus.infrastructure.resource_contracts import count as resource_count, object_limits, timeout as resource_timeout
from korpus.infrastructure.object_store import (
    BUCKET_PATTERN,
    DEFAULT_MAX_OBJECT_BYTES,
    HASH_PATTERN,
    KEY_PATTERN,
    PREFIX_PATTERN,
)
_STORAGE_API = "https://storage.googleapis.com"
_JSON_API = f"{_STORAGE_API}/storage/v1"
_UPLOAD_API = f"{_STORAGE_API}/upload/storage/v1"
_DOWNLOAD_API = f"{_STORAGE_API}/download/storage/v1"


class GcsPreconditionFailed(RuntimeError):
    pass


class GcsJsonClient:
    """Minimal GCS JSON API client using Cloud Run workload identity.

    The client intentionally implements only the operations KORPUS needs. No service
    account key, HMAC key, signed URL, or ambient gcloud credential is accepted.
    """

    def __init__(
        self,
        bucket: str,
        *,
        identity: MetadataIdentityProvider | None = None,
        timeout_seconds: float = 20.0,
        client: Any | None = None,
    ) -> None:
        timeout_seconds = resource_timeout(timeout_seconds, "timeout_seconds")
        if not BUCKET_PATTERN.fullmatch(bucket): raise ValueError("invalid GCS configuration")
        self.bucket = bucket
        self.identity = identity or MetadataIdentityProvider()
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
            follow_redirects=False,
        )

    def upload_create_only(self, name: str, content: bytes) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"{_UPLOAD_API}/b/{quote(self.bucket, safe='')}/o",
            params={"uploadType": "media", "name": name, "ifGenerationMatch": "0"},
            headers={"Content-Type": "application/octet-stream"},
            content=content,
            allow_precondition=True,
        )
        if response.status_code == 412:
            raise GcsPreconditionFailed("GCS create-only precondition failed")
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise ObjectStoreUnavailable("GCS upload returned invalid metadata") from exc
        if str(payload.get("name", "")) != name:
            raise ObjectStoreUnavailable("GCS upload metadata does not identify the object")
        return payload

    def download(self, name: str) -> bytes:
        response = self._request(
            "GET",
            f"{_DOWNLOAD_API}/b/{quote(self.bucket, safe='')}/o/{quote(name, safe='')}",
            params={"alt": "media"},
        )
        return bytes(response.content)

    def metadata(self, name: str) -> dict[str, Any] | None:
        response = self._request(
            "GET",
            f"{_JSON_API}/b/{quote(self.bucket, safe='')}/o/{quote(name, safe='')}",
            params={"fields": "bucket,name,size,generation"},
            allow_not_found=True,
        )
        if response.status_code == 404:
            return None
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise ObjectStoreUnavailable("GCS metadata response is invalid") from exc
        return dict(payload)

    def list_names(self, prefix: str, *, max_results: int | None = None) -> list[str]:
        names: list[str] = []
        page_token: str | None = None
        while True:
            params: dict[str, str] = {"prefix": prefix, "fields": "items/name,nextPageToken"}
            if page_token:
                params["pageToken"] = page_token
            if max_results is not None:
                remaining = max_results - len(names)
                if remaining <= 0:
                    break
                params["maxResults"] = str(min(1000, remaining))
            response = self._request(
                "GET",
                f"{_JSON_API}/b/{quote(self.bucket, safe='')}/o",
                params=params,
            )
            try:
                payload = response.json()
            except (TypeError, ValueError) as exc:
                raise ObjectStoreUnavailable("GCS list response is invalid") from exc
            for item in payload.get("items", []) or []:
                name = str(item.get("name", ""))
                if name:
                    names.append(name)
                    if max_results is not None and len(names) >= max_results:
                        return names
            page_token = str(payload.get("nextPageToken", "")) or None
            if not page_token:
                return names
        return names

    def bucket_metadata(self) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"{_JSON_API}/b/{quote(self.bucket, safe='')}",
            params={"fields": "name,retentionPolicy,versioning"},
        )
        try:
            return dict(response.json())
        except (TypeError, ValueError) as exc:
            raise ObjectStoreUnavailable("GCS bucket metadata response is invalid") from exc

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
        self.identity.close()

    def _request(
        self,
        method: str,
        url: str,
        *,
        allow_not_found: bool = False,
        allow_precondition: bool = False,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        request_headers = {"Authorization": self.identity.authorization_header()}
        if headers:
            request_headers.update(headers)
        try:
            response = self.client.request(method, url, headers=request_headers, **kwargs)
        except (httpx.HTTPError, MetadataIdentityError, OSError) as exc:
            raise ObjectStoreUnavailable("GCS transport is unavailable") from exc
        if allow_not_found and response.status_code == 404:
            return response
        if allow_precondition and response.status_code == 412:
            return response
        if response.status_code == 429 or 500 <= response.status_code <= 599:
            raise ObjectStoreUnavailable(f"GCS transient failure: {response.status_code}")
        try:
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"GCS request failed: {response.status_code}") from exc
        return response


class GcsObjectStore:
    """Create-only, content-addressed GCS store with SHA-256 verification on every read."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "objects",
        retention_seconds: int = 0,
        max_object_bytes: int = DEFAULT_MAX_OBJECT_BYTES,
        gcs: GcsJsonClient | None = None,
    ) -> None:
        normalized_prefix = prefix.strip("/")
        retention_seconds, max_object_bytes = object_limits(retention_seconds, max_object_bytes)
        if (
            not BUCKET_PATTERN.fullmatch(bucket)
            or (
                normalized_prefix
                and (
                    not PREFIX_PATTERN.fullmatch(normalized_prefix)
                    or ".." in normalized_prefix.split("/")
                )
            )
        ):
            raise ValueError("invalid GCS object store configuration")
        self.bucket = bucket
        self.prefix = normalized_prefix
        self.retention_seconds = retention_seconds
        self.max_object_bytes = max_object_bytes
        self.gcs = gcs or GcsJsonClient(bucket)

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

    def put(self, content: bytes, source_hash: str, filename: str) -> str:
        del filename
        if len(content) > self.max_object_bytes:
            raise ValueError("object exceeds configured size limit")
        if hashlib.sha256(content).hexdigest() != source_hash:
            raise ValueError("source hash does not match content")
        key = self._key(source_hash)
        try:
            self.gcs.upload_create_only(key, content)
        except GcsPreconditionFailed:
            # Idempotent replay: the object already exists. Verify that the
            # immutable remote object is exactly the requested payload before
            # accepting the precondition failure as success.
            self._verify_remote(key, source_hash, len(content))
            return key
        self._verify_remote(key, source_hash, len(content))
        return key

    def put_path(self, path: Path, source_hash: str, filename: str) -> str:
        del filename
        if path.stat().st_size > self.max_object_bytes:
            raise ValueError("object exceeds configured size limit")
        content = path.read_bytes()
        return self.put(content, source_hash, path.name)

    def get(self, object_key: str) -> bytes:
        source_hash = self._validate_key(object_key)
        metadata = self.gcs.metadata(object_key)
        if metadata is None:
            raise FileNotFoundError(object_key)
        declared_size = resource_count(metadata.get("size", 0), 0, "GCS object size", allow_digit_string=True)
        if declared_size > self.max_object_bytes:
            raise RuntimeError("GCS object exceeds configured read limit")
        content = self.gcs.download(object_key)
        if len(content) > self.max_object_bytes:
            raise RuntimeError("GCS object exceeds configured read limit")
        if hashlib.sha256(content).hexdigest() != source_hash:
            raise RuntimeError("GCS object integrity verification failed")
        return content

    def get_to_path(self, object_key: str, destination: Path) -> None:
        content = self.get(object_key)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def exists(self, object_key: str) -> bool:
        self._validate_key(object_key)
        return self.gcs.metadata(object_key) is not None

    def list_keys(self) -> set[str]:
        prefix = f"{self.prefix}/" if self.prefix else ""
        keys: set[str] = set()
        for key in self.gcs.list_names(prefix):
            self._validate_key(key)
            keys.add(key)
        return keys

    def healthcheck(self) -> bool:
        try:
            metadata = self.gcs.bucket_metadata()
            if metadata.get("name") != self.bucket:
                return False
            if self.retention_seconds:
                policy = metadata.get("retentionPolicy") or {}
                if int(policy.get("retentionPeriod", 0)) < self.retention_seconds:
                    return False
            return True
        except Exception:
            return False

    def close(self) -> None:
        self.gcs.close()

    def _verify_remote(self, key: str, source_hash: str, content_length: int) -> None:
        metadata = self.gcs.metadata(key)
        if metadata is None:
            raise RuntimeError("GCS object missing after write")
        if int(metadata.get("size", -1)) != content_length:
            raise RuntimeError("GCS content length mismatch")
        content = self.gcs.download(key)
        if hashlib.sha256(content).hexdigest() != source_hash:
            raise RuntimeError("GCS object integrity verification failed")
