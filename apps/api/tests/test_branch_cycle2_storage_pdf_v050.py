from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from korpus.infrastructure import object_store as osmod
from korpus.infrastructure import pdf_extraction as pdf


class Missing(Exception):
    response = {"Error": {"Code": "404"}}


class Body:
    def __init__(self, data: bytes, *, close_callable: bool = True) -> None:
        self._io = BytesIO(data)
        self.closed_called = False
        if not close_callable:
            self.close = None  # type: ignore[assignment]

    def read(self, n: int = -1) -> bytes:
        return self._io.read(n)

    def close(self) -> None:
        self.closed_called = True


class S3:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.return_missing_after_write = False
        self.closed = False
        self.versioning = "Enabled"
        self.lock = "Enabled"
        self.raise_list: Exception | None = None
        self.pages: list[dict] = []

    def head_object(self, *, Bucket: str, Key: str, **kwargs):
        del Bucket, kwargs
        if self.return_missing_after_write:
            raise Missing()
        try:
            return dict(self.objects[Key]["head"])
        except KeyError as exc:
            raise Missing() from exc

    def put_object(self, **kwargs):
        body = kwargs["Body"]
        data = body.read() if hasattr(body, "read") else bytes(body)
        self.objects[kwargs["Key"]] = {
            "data": data,
            "head": {
                "Metadata": dict(kwargs["Metadata"]),
                "ContentLength": len(data),
                "ChecksumSHA256": kwargs.get("ChecksumSHA256"),
            },
        }

    def get_object(self, *, Bucket: str, Key: str, ChecksumMode: str):
        del Bucket, ChecksumMode
        item = self.objects[Key]
        head = item["head"]
        return {
            "Body": Body(item["data"]),
            "Metadata": dict(head.get("Metadata", {})),
            "ContentLength": head.get("ContentLength", len(item["data"])),
            "ChecksumSHA256": head.get("ChecksumSHA256"),
        }

    def list_objects_v2(self, **kwargs):
        del kwargs
        if self.raise_list:
            raise self.raise_list
        if self.pages:
            return self.pages.pop(0)
        return {"Contents": [], "IsTruncated": False}

    def get_bucket_versioning(self, **kwargs):
        del kwargs
        return {"Status": self.versioning}

    def get_object_lock_configuration(self, **kwargs):
        del kwargs
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": self.lock}}

    def close(self):
        self.closed = True


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_local_store_cleanup_collision_bounds_and_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = osmod.LocalObjectStore(tmp_path / "objects", max_object_bytes=8)
    data = b"abc"
    digest = _digest(data)

    with pytest.raises(ValueError, match="invalid source hash"):
        store.put_path(tmp_path / "missing", "bad", "x")

    source = tmp_path / "source"
    source.write_bytes(data)
    key = store.put_path(source, digest, "x")
    (store.root / key).write_bytes(b"bad")
    with pytest.raises(RuntimeError, match="collision"):
        store.put_path(source, digest, "x")

    big = b"0123456789"
    big_digest = _digest(big)
    target = store.root / big_digest[:2] / big_digest[2:4] / big_digest
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(big)
    with pytest.raises(RuntimeError, match="read limit"):
        store.get_to_path(f"{big_digest[:2]}/{big_digest[2:4]}/{big_digest}", tmp_path / "out")

    # Force the atomic-write failure path so the finally block removes the temp file.
    cleanup_store = osmod.LocalObjectStore(tmp_path / "cleanup")
    real_replace = osmod.os.replace
    monkeypatch.setattr(osmod.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError, match="boom"):
        cleanup_store.put(data, digest, "x")
    assert not list((cleanup_store.root / digest[:2] / digest[2:4]).glob(".object-*"))
    monkeypatch.setattr(osmod.os, "replace", real_replace)

    # A symlink inside the root must not turn a syntactically valid key into traversal.
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "escape-root"
    escape = osmod.LocalObjectStore(root)
    (root / digest[:2]).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        escape.get(f"{digest[:2]}/{digest[2:4]}/{digest}")


def test_s3_key_head_and_verifier_refusal_matrix() -> None:
    client = S3()
    store = osmod.S3ObjectStore(bucket="bucket", prefix="objects", client=client)
    data = b"payload"
    digest = _digest(data)
    encoded = base64.b64encode(bytes.fromhex(digest)).decode("ascii")

    with pytest.raises(ValueError, match="invalid source hash"):
        store._key("bad")
    with pytest.raises(ValueError, match="outside configured prefix"):
        store._validate_key(f"other/{digest[:2]}/{digest[2:4]}/{digest}")
    with pytest.raises(ValueError, match="invalid object key"):
        store._validate_key("objects/not-a-key")

    with pytest.raises(RuntimeError, match="metadata"):
        store._verify_head({"Metadata": {"sha256": "b" * 64}}, digest)
    with pytest.raises(RuntimeError, match="checksum"):
        store._verify_head({"Metadata": {"sha256": digest}, "ChecksumSHA256": "wrong"}, digest)
    with pytest.raises(RuntimeError, match="length"):
        store._verify_head(
            {"Metadata": {"sha256": digest}, "ChecksumSHA256": encoded, "ContentLength": 99},
            digest,
            len(data),
        )
    store._verify_head({"Metadata": {"sha256": digest}}, digest, len(data))


def test_s3_put_put_path_retention_existing_and_missing(tmp_path: Path) -> None:
    data = b"payload"
    digest = _digest(data)
    client = S3()
    store = osmod.S3ObjectStore(
        bucket="bucket", prefix="objects", governance_retention_days=1, client=client
    )
    key = store.put(data, digest, "x")
    assert client.objects[key]["head"]["Metadata"]["sha256"] == digest
    assert store.put(data, digest, "x") == key  # existing-head branch

    path = tmp_path / "p"
    path.write_bytes(data)
    assert store.put_path(path, digest, "x") == key
    with pytest.raises(ValueError, match="size limit"):
        osmod.S3ObjectStore(bucket="bucket", client=S3(), max_object_bytes=1).put_path(path, digest, "x")
    with pytest.raises(ValueError, match="does not match file"):
        osmod.S3ObjectStore(bucket="bucket", client=S3()).put_path(path, "a" * 64, "x")

    client2 = S3()
    client2.return_missing_after_write = True
    missing = osmod.S3ObjectStore(bucket="bucket", governance_retention_days=1, client=client2)
    with pytest.raises(RuntimeError, match="missing after write"):
        missing.put(data, digest, "x")
    client3 = S3()
    client3.return_missing_after_write = True
    missing_path = osmod.S3ObjectStore(bucket="bucket", governance_retention_days=1, client=client3)
    with pytest.raises(RuntimeError, match="missing after write"):
        missing_path.put_path(path, digest, "x")


def test_s3_get_and_stream_refusal_matrix(tmp_path: Path) -> None:
    data = b"payload"
    digest = _digest(data)
    key = f"objects/{digest[:2]}/{digest[2:4]}/{digest}"
    encoded = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
    client = S3()
    client.objects[key] = {
        "data": data,
        "head": {"Metadata": {"sha256": digest}, "ContentLength": len(data), "ChecksumSHA256": encoded},
    }
    store = osmod.S3ObjectStore(bucket="bucket", prefix="objects", client=client, max_object_bytes=64)
    assert store.get(key) == data

    # declared oversize with a body whose close attribute is not callable
    store.client.get_object = lambda **kw: {"Body": Body(data, close_callable=False), "Metadata": {"sha256": digest}, "ContentLength": 999}
    with pytest.raises(RuntimeError, match="read limit"):
        store.get(key)
    with pytest.raises(RuntimeError, match="read limit"):
        store.get_to_path(key, tmp_path / "declared")

    # no ContentLength => streaming bound is authoritative
    store.client.get_object = lambda **kw: {"Body": Body(b"x" * 65), "Metadata": {"sha256": digest}}
    with pytest.raises(RuntimeError, match="read limit"):
        store.get(key)
    with pytest.raises(RuntimeError, match="read limit"):
        store.get_to_path(key, tmp_path / "overflow")

    # checksum/metadata/content refusal paths on bounded streams.
    store.client.get_object = lambda **kw: {"Body": Body(data), "Metadata": {"sha256": digest}, "ChecksumSHA256": "bad"}
    with pytest.raises(RuntimeError, match="response checksum"):
        store.get(key)
    with pytest.raises(RuntimeError, match="response checksum"):
        store.get_to_path(key, tmp_path / "checksum")

    store.client.get_object = lambda **kw: {"Body": Body(data), "Metadata": {"sha256": "b" * 64}}
    with pytest.raises(RuntimeError, match="metadata"):
        store.get_to_path(key, tmp_path / "metadata")

    store.client.get_object = lambda **kw: {"Body": Body(b"tamper"), "Metadata": {"sha256": digest}}
    with pytest.raises(RuntimeError, match="integrity"):
        store.get_to_path(key, tmp_path / "integrity")


def test_s3_inventory_health_and_close_edges() -> None:
    digest = "a" * 64
    valid = f"objects/aa/aa/{digest}"
    client = S3()
    store = osmod.S3ObjectStore(bucket="bucket", prefix="objects", governance_retention_days=1, client=client)
    client.pages = [
        {"Contents": [{"Key": ""}, {"Key": valid}], "IsTruncated": True, "NextContinuationToken": "n"},
        {"Contents": [], "IsTruncated": False},
    ]
    assert store.list_keys() == {valid}
    client.versioning = "Suspended"
    assert store.healthcheck() is False
    client.versioning = "Enabled"
    client.lock = "Disabled"
    assert store.healthcheck() is False
    client.lock = "Enabled"
    client.raise_list = RuntimeError("down")
    assert store.healthcheck() is False
    client.raise_list = None
    store.close()
    assert client.closed

    # close is optional for injected lightweight clients.
    no_close = SimpleNamespace(list_objects_v2=lambda **k: {"Contents": [], "IsTruncated": False})
    osmod.S3ObjectStore(bucket="bucket", client=no_close).close()


def test_pdf_open_embedded_ocr_branch_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "x.pdf"
    path.write_bytes(b"pdf")

    class Page:
        def __init__(self, text: str | None = None, exc: Exception | None = None):
            self.text, self.exc = text, exc
        def extract_text(self):
            if self.exc:
                raise self.exc
            return self.text

    class Reader:
        def __init__(self, pages, *, encrypted=False, decrypt_result=1, decrypt_exc=None):
            self.pages = pages
            self.is_encrypted = encrypted
            self._decrypt_result = decrypt_result
            self._decrypt_exc = decrypt_exc
        def decrypt(self, value):
            del value
            if self._decrypt_exc:
                raise self._decrypt_exc
            return self._decrypt_result

    with pytest.raises(ValueError, match="malformed PDF"):
        pdf._open_pdf(path, 2, lambda *a, **k: (_ for _ in ()).throw(OSError("bad")))
    with pytest.raises(ValueError, match="unsupported algorithm"):
        pdf._open_pdf(path, 2, lambda *a, **k: Reader([], encrypted=True, decrypt_exc=ValueError("x")))
    with pytest.raises(ValueError, match="requires a password"):
        pdf._open_pdf(path, 2, lambda *a, **k: Reader([], encrypted=True, decrypt_result=0))
    with pytest.raises(ValueError, match="page count"):
        pdf._open_pdf(path, 1, lambda *a, **k: Reader([Page(), Page()]))

    assert pdf._embedded_pages(Reader([Page(" A ")]), 10**12, lambda s: s.strip())[0].text == "A"
    with pytest.raises(ValueError, match="text extraction"):
        pdf._embedded_pages(Reader([Page(exc=TypeError("bad"))]), 10**12, str)
    with pytest.raises(ValueError, match="time budget"):
        pdf._remaining(-1)

    # High embedded-text fast path, both owner-restricted and ordinary.
    rich = "x" * 100
    pages, method = pdf.extract_pdf_pages(path, False, "eng", str, max_pdf_pages=2, ocr_total_timeout_seconds=5, reader_factory=lambda *a, **k: Reader([Page(rich)]))
    assert pages and method == "pdf_text"
    _, method = pdf.extract_pdf_pages(path, False, "eng", str, max_pdf_pages=2, ocr_total_timeout_seconds=5, reader_factory=lambda *a, **k: Reader([Page(rich)], encrypted=True))
    assert method == "pdf_text_owner_restricted"

    with pytest.raises(ValueError, match="OCR is disabled"):
        pdf.extract_pdf_pages(path, False, "eng", str, max_pdf_pages=2, ocr_total_timeout_seconds=5, reader_factory=lambda *a, **k: Reader([Page("")]))

    monkeypatch.setattr(pdf, "_ocr_pages", lambda *a, **k: [])
    with pytest.raises(ValueError, match="no text"):
        pdf.extract_pdf_pages(path, True, "eng", str, max_pdf_pages=2, ocr_total_timeout_seconds=5, reader_factory=lambda *a, **k: Reader([Page("")]))
    monkeypatch.setattr(pdf, "_ocr_pages", lambda *a, **k: [SimpleNamespace(page=1, text="ocr")])
    _, method = pdf.extract_pdf_pages(path, True, "eng", str, max_pdf_pages=2, ocr_total_timeout_seconds=5, reader_factory=lambda *a, **k: Reader([Page("")], encrypted=True))
    assert method == "pdf_ocr_owner_restricted"
    monkeypatch.setattr(pdf, "_ocr_pages", lambda *a, **k: (_ for _ in ()).throw(OSError("ocr")))
    with pytest.raises(ValueError, match="OCR execution failed"):
        pdf.extract_pdf_pages(path, True, "eng", str, max_pdf_pages=2, ocr_total_timeout_seconds=5, reader_factory=lambda *a, **k: Reader([Page("")]))
