import hashlib
from io import BytesIO
from typing import ClassVar

import pytest
from korpus.infrastructure.object_store import S3ObjectStore


class NotFound(Exception):
    # botocore raises client errors carrying a shared `response` mapping on the class.
    # ClassVar states the sharing that already exists; it does not move the attribute.
    response: ClassVar[dict[str, dict[str, str]]] = {"Error": {"Code": "404"}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.puts = []

    def head_object(self, Bucket, Key):
        try:
            item = self.objects[(Bucket, Key)]
        except KeyError as missing:
            raise NotFound() from missing
        return {"Metadata": item["Metadata"]}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "Body": bytes(kwargs["Body"]),
            "Metadata": kwargs["Metadata"],
        }

    def get_object(self, Bucket, Key, ChecksumMode):
        item = self.objects[(Bucket, Key)]
        return {
            "Body": BytesIO(item["Body"]),
            "Metadata": item["Metadata"],
            "ContentLength": len(item["Body"]),
        }

    def list_objects_v2(self, Bucket, Prefix, MaxKeys):
        return {"KeyCount": 0}

    def get_bucket_versioning(self, Bucket):
        return {"Status": "Enabled"}

    def get_object_lock_configuration(self, Bucket):
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}


def test_s3_store_is_content_addressed_idempotent_and_integrity_checked():
    client = FakeS3()
    store = S3ObjectStore(bucket="bucket", prefix="objects", client=client)
    content = b"authoritative source"
    digest = hashlib.sha256(content).hexdigest()
    key = store.put(content, digest, "../../evil.pdf")
    assert store.put(content, digest, "other.pdf") == key
    assert len(client.puts) == 1
    assert client.puts[0]["ServerSideEncryption"] == "AES256"
    assert store.get(key) == content
    client.objects[("bucket", key)]["Body"] = b"tampered"
    with pytest.raises(RuntimeError, match="integrity"):
        store.get(key)


def test_s3_store_rejects_hash_mismatch():
    with pytest.raises(ValueError):
        S3ObjectStore(bucket="bucket", client=FakeS3()).put(b"x", "a" * 64, "x")


def test_s3_store_rejects_unsafe_prefix_and_bounded_reads():
    with pytest.raises(ValueError, match="invalid S3"):
        S3ObjectStore(bucket="bucket", prefix="../escape", client=FakeS3())
    client = FakeS3()
    store = S3ObjectStore(bucket="bucket", prefix="objects", max_object_bytes=4, client=client)
    content = b"12345"
    digest = hashlib.sha256(content).hexdigest()
    with pytest.raises(ValueError, match="size limit"):
        store.put(content, digest, "x")
    key = store._key(digest)
    client.objects[("bucket", key)] = {"Body": content, "Metadata": {"sha256": digest}}
    with pytest.raises(RuntimeError, match="read limit"):
        store.get(key)


def test_s3_healthchecks_application_prefix_permission():
    assert S3ObjectStore(bucket="bucket", prefix="objects", client=FakeS3()).healthcheck() is True


def test_s3_healthcheck_requires_versioning_and_object_lock_when_retention_enabled():
    client = FakeS3()
    store = S3ObjectStore(
        bucket="bucket", prefix="objects", governance_retention_days=30, client=client
    )
    assert store.healthcheck() is True
    client.get_bucket_versioning = lambda Bucket: {"Status": "Suspended"}
    assert store.healthcheck() is False
