import hashlib
from io import BytesIO

import pytest

from korpus.infrastructure.object_store import S3ObjectStore


class NotFound(Exception):
    response = {"Error": {"Code": "404"}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.puts = []

    def head_object(self, Bucket, Key):
        try:
            item = self.objects[(Bucket, Key)]
        except KeyError:
            raise NotFound()
        return {"Metadata": item["Metadata"]}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "Body": bytes(kwargs["Body"]),
            "Metadata": kwargs["Metadata"],
        }

    def get_object(self, Bucket, Key, ChecksumMode):
        item = self.objects[(Bucket, Key)]
        return {"Body": BytesIO(item["Body"]), "Metadata": item["Metadata"]}


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
