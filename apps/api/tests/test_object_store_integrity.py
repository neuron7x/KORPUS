"""Content addressing only means something if the address is verified on the way out.

`LocalObjectStore` names every object by the sha256 of its bytes. That buys nothing on
its own: the guarantee comes from re-hashing on read and refusing when the answer
disagrees, from refusing a key that walks out of the store root, and from writing
through a temporary file so a crash cannot leave a partial object under a name that
claims to be a complete one.

Those refusal paths had no tests. An integrity check nothing has ever caught anything
with is the same artefact as no integrity check — both return the bytes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from korpus.infrastructure.object_store import LocalObjectStore

CONTENT = b"Order No. 1. Basis: article 5.\n"
DIGEST = hashlib.sha256(CONTENT).hexdigest()


def _store(tmp_path: Path, **kwargs: object) -> LocalObjectStore:
    return LocalObjectStore(tmp_path / "objects", **kwargs)


def test_an_object_round_trips_under_its_content_address(tmp_path: Path) -> None:
    """The dual: every refusal below is vacuous if nothing round-trips."""
    store = _store(tmp_path)

    key = store.put(CONTENT, DIGEST, "order.txt")

    assert key.endswith(DIGEST)
    assert store.get(key) == CONTENT
    assert store.exists(key)


def test_the_store_refuses_to_be_created_with_a_nonsensical_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _store(tmp_path, max_object_bytes=0)


def test_the_store_root_is_not_world_readable(tmp_path: Path) -> None:
    """Corpus bytes are classified material; the directory mode is part of the control."""
    store = _store(tmp_path)

    assert (store.root.stat().st_mode & 0o777) == 0o700


@pytest.mark.parametrize("digest", ["", "not-a-hash", "abc", "g" * 64, DIGEST.upper()])
def test_a_malformed_source_hash_is_refused(digest: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid source hash"):
        _store(tmp_path).put(CONTENT, digest, "order.txt")


def test_content_that_does_not_match_its_declared_hash_is_refused(tmp_path: Path) -> None:
    """The caller's claim about the bytes is checked against the bytes."""
    with pytest.raises(ValueError, match="does not match content"):
        _store(tmp_path).put(b"different bytes", DIGEST, "order.txt")


def test_storing_the_same_object_twice_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)

    first = store.put(CONTENT, DIGEST, "order.txt")
    second = store.put(CONTENT, DIGEST, "order.txt")

    assert first == second
    assert store.get(first) == CONTENT


def test_an_object_altered_on_disk_is_refused_on_read(tmp_path: Path) -> None:
    """The case the whole design exists for: bytes changed under a name that claims them."""
    store = _store(tmp_path)
    key = store.put(CONTENT, DIGEST, "order.txt")
    (store.root / key).write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="integrity verification failed"):
        store.get(key)


def test_an_altered_object_is_refused_when_streamed_to_a_path(tmp_path: Path) -> None:
    """The streaming reader must verify too, or the large-file path is unguarded."""
    store = _store(tmp_path)
    key = store.put(CONTENT, DIGEST, "order.txt")
    (store.root / key).write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="integrity verification failed"):
        store.get_to_path(key, tmp_path / "out" / "order.txt")


def test_a_failed_stream_leaves_no_partial_file_behind(tmp_path: Path) -> None:
    """A partial download under the destination name would read as a complete object."""
    store = _store(tmp_path)
    key = store.put(CONTENT, DIGEST, "order.txt")
    (store.root / key).write_bytes(b"tampered")
    destination = tmp_path / "out" / "order.txt"

    with pytest.raises(RuntimeError):
        store.get_to_path(key, destination)

    assert not destination.exists()
    assert list((tmp_path / "out").glob(".download-*")) == []


def test_a_valid_stream_writes_the_verified_bytes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    key = store.put(CONTENT, DIGEST, "order.txt")
    destination = tmp_path / "out" / "order.txt"

    store.get_to_path(key, destination)

    assert destination.read_bytes() == CONTENT


@pytest.mark.parametrize(
    "key",
    [
        "../../etc/passwd",
        "ab/cd/../../../../etc/passwd",
        "not-a-key",
        "ab/cd/" + "z" * 64,
        "",
    ],
)
def test_a_key_that_is_not_a_content_address_is_refused(key: str, tmp_path: Path) -> None:
    """Path traversal through an object key would read anything the process can."""
    store = _store(tmp_path)

    with pytest.raises(ValueError, match=r"invalid object key|escapes store root"):
        store.get(key)


def test_an_object_larger_than_the_limit_is_refused_on_write(tmp_path: Path) -> None:
    store = _store(tmp_path, max_object_bytes=8)
    big = b"x" * 64

    with pytest.raises(ValueError, match="exceeds configured size limit"):
        store.put_path(_written(tmp_path, big), hashlib.sha256(big).hexdigest(), "big.bin")


def test_an_object_larger_than_the_limit_is_refused_on_read(tmp_path: Path) -> None:
    """The limit must hold for objects already stored, not only for new ones."""
    store = _store(tmp_path)
    key = store.put(CONTENT, DIGEST, "order.txt")
    bounded = _store(tmp_path, max_object_bytes=4)

    with pytest.raises(RuntimeError, match="exceeds configured read limit"):
        bounded.get(key)


def _written(tmp_path: Path, content: bytes) -> Path:
    path = tmp_path / "incoming.bin"
    path.write_bytes(content)
    return path


def test_put_path_stores_and_verifies_a_file(tmp_path: Path) -> None:
    store = _store(tmp_path)

    key = store.put_path(_written(tmp_path, CONTENT), DIGEST, "order.txt")

    assert store.get(key) == CONTENT


def test_put_path_refuses_a_file_whose_bytes_are_not_the_declared_hash(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises((ValueError, RuntimeError)):
        store.put_path(_written(tmp_path, b"other"), DIGEST, "order.txt")


def test_listing_reports_content_addresses_and_ignores_working_files(tmp_path: Path) -> None:
    """Reconciliation compares this list with the database; noise there reads as drift."""
    store = _store(tmp_path)
    key = store.put(CONTENT, DIGEST, "order.txt")
    (store.root / ".partial-upload").write_bytes(b"junk")
    (store.root / "loose.txt").write_bytes(b"junk")

    assert store.list_keys() == {key}


def test_healthcheck_reports_a_writable_store(tmp_path: Path) -> None:
    assert _store(tmp_path).healthcheck() is True
