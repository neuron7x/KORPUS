from __future__ import annotations

import json
from typing import Any

import pytest
from korpus.infrastructure.audit_anchor import AnchorError
from korpus.infrastructure.gcs import GcsPreconditionFailed
from korpus.infrastructure.gcs_audit_anchor import GcsAuditAnchorStore


class MemoryGcs:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload_create_only(self, name: str, content: bytes) -> dict[str, Any]:
        if name in self.objects:
            raise GcsPreconditionFailed("exists")
        self.objects[name] = bytes(content)
        return {"name": name, "size": str(len(content)), "generation": "1"}

    def download(self, name: str) -> bytes:
        return self.objects[name]

    def list_names(self, prefix: str, *, max_results: int | None = None) -> list[str]:
        names = sorted(name for name in self.objects if name.startswith(prefix))
        return names if max_results is None else names[:max_results]

    def close(self) -> None:
        pass


def anchor(backend: MemoryGcs | None = None) -> tuple[GcsAuditAnchorStore, MemoryGcs]:
    gcs = backend or MemoryGcs()
    return GcsAuditAnchorStore("korpus-audit", b"a" * 40, gcs=gcs), gcs  # type: ignore[arg-type]


def test_gcs_anchor_is_append_only_and_monotonic() -> None:
    store, backend = anchor()
    assert store.read().sequence == 0
    store.write(1, "1" * 64)
    store.write(3, "3" * 64)
    store.write(2, "2" * 64)
    assert store.read().sequence == 3
    assert len(backend.objects) == 2
    assert all(name.endswith(".json") for name in backend.objects)


def test_gcs_anchor_same_sequence_is_idempotent_but_conflict_is_refused() -> None:
    store, _ = anchor()
    store.write(7, "7" * 64)
    store.write(7, "7" * 64)
    with pytest.raises(AnchorError, match="conflicting"):
        store.write(7, "8" * 64)


def test_gcs_anchor_detects_payload_tampering() -> None:
    store, backend = anchor()
    store.write(2, "2" * 64)
    name = next(iter(backend.objects))
    payload = json.loads(backend.objects[name])
    payload["head_hash"] = "f" * 64
    backend.objects[name] = json.dumps(payload).encode()
    with pytest.raises(AnchorError, match="MAC mismatch"):
        store.read()


def test_gcs_anchor_refuses_malformed_inventory_and_reset() -> None:
    store, backend = anchor()
    backend.objects["audit/anchors/not-a-sequence.json"] = b"{}"
    with pytest.raises(AnchorError, match="invalid sequence"):
        store.read()
    with pytest.raises(AnchorError, match="reset is forbidden"):
        store.reset()


def test_a_prefix_that_could_escape_the_anchor_namespace_is_refused() -> None:
    """The prefix becomes an object path. `..` in it writes anchors somewhere else.

    A locked retention policy is scoped to a prefix; anchors written outside it are
    ordinary mutable objects, so the append-only property this class exists to provide
    would hold for a path nobody is watching.
    """
    for hostile in ("", "/", "///", "../audit", "audit/../../etc", ".."):
        with pytest.raises(ValueError, match="invalid GCS audit anchor prefix"):
            GcsAuditAnchorStore("korpus-audit", b"a" * 40, prefix=hostile, gcs=MemoryGcs())  # type: ignore[arg-type]

    # A prefix that only needs trimming is normalised rather than refused.
    _, backend = anchor()
    forgiving = GcsAuditAnchorStore("korpus-audit", b"a" * 40, prefix="/audit/anchors/", gcs=backend)  # type: ignore[arg-type]
    assert forgiving.prefix == "audit/anchors"


@pytest.mark.parametrize("sequence", [-1, -(10**9), 10**32, 10**40])
def test_a_sequence_outside_the_representable_range_is_refused(sequence: int) -> None:
    """Object names are zero-padded to 32 digits; a longer one sorts before a shorter."""
    store, _ = anchor()
    with pytest.raises(AnchorError, match="outside supported range"):
        store.write(sequence, "a" * 64)


class RaceLostGcs(MemoryGcs):
    """A bucket whose listing is stale: the object appears only when we try to create it.

    This is the real shape of the race the precondition guards. `write` reads the
    inventory, decides the sequence is free, and the competing writer's object lands
    first — so the failure arrives from `upload_create_only`, not from the read.
    """

    def __init__(self, planted: dict[str, bytes]) -> None:
        super().__init__()
        self._planted = planted

    def upload_create_only(self, name: str, content: bytes) -> Any:
        if name in self._planted:
            self.objects[name] = self._planted[name]
            raise GcsPreconditionFailed("exists")
        return super().upload_create_only(name, content)


def _encoded(store: GcsAuditAnchorStore, sequence: int, head: str) -> bytes:
    return json.dumps(
        store.codec.encode(sequence, head), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def test_a_racing_writer_that_wrote_the_same_hash_is_accepted() -> None:
    """Two processes anchoring the same head is normal; only disagreement is a fault."""
    reference, _ = anchor()
    name = reference._name(5)
    backend = RaceLostGcs({name: _encoded(reference, 5, "5" * 64)})
    store, _ = anchor(backend)
    store.write(5, "5" * 64)
    assert store.read().head_hash == "5" * 64


def test_a_racing_writer_that_wrote_a_different_hash_is_refused() -> None:
    """`ifGenerationMatch=0` gives the object to the first writer; the second must agree.

    Without this check the loser would treat the precondition failure as success and
    continue on a head hash that is not what the bucket holds — two chains, one of them
    invisible.
    """
    reference, _ = anchor()
    name = reference._name(5)
    backend = RaceLostGcs({name: _encoded(reference, 5, "a" * 64)})
    store, _ = anchor(backend)
    with pytest.raises(AnchorError, match="rejected conflicting sequence"):
        store.write(5, "b" * 64)


def test_a_write_the_bucket_did_not_keep_is_refused() -> None:
    """Read-after-write: an upload that reports success and stores something else."""

    class LyingGcs(MemoryGcs):
        def upload_create_only(self, name: str, content: bytes) -> dict[str, Any]:
            store, _ = anchor()
            substituted = json.dumps(
                store.codec.encode(9, "0" * 64), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            return super().upload_create_only(name, substituted)

    store, _ = anchor(LyingGcs())
    with pytest.raises(AnchorError, match="failed post-write verification"):
        store.write(9, "9" * 64)


def test_a_payload_whose_sequence_contradicts_its_object_name_is_refused() -> None:
    """The name is the index and the payload is the claim; a mismatch is a rewrite."""
    store, backend = anchor()
    store.write(4, "4" * 64)
    name = store._name(4)
    backend.objects[store._name(6)] = backend.objects.pop(name)
    with pytest.raises(AnchorError, match="name/payload sequence mismatch"):
        store.read()


@pytest.mark.parametrize(
    "bad_name",
    [
        "audit/anchors/not-a-number.json",
        "audit/anchors/123.json",
        "audit/anchors/0000000000000000000000000000000x.json",
        "audit/anchors/00000000000000000000000000000001.txt",
    ],
)
def test_an_inventory_entry_that_is_not_an_anchor_name_is_refused(bad_name: str) -> None:
    """`max()` over parsed sequences must not silently skip what it cannot parse."""
    store, backend = anchor()
    backend.objects[bad_name] = b"{}"
    with pytest.raises(AnchorError, match="invalid"):
        store.read()


def test_reset_is_refused_because_append_only_has_no_undo() -> None:
    store, _ = anchor()
    with pytest.raises(AnchorError, match="reset is forbidden"):
        store.reset()


def test_a_bucket_name_the_api_would_reject_is_refused_before_any_request() -> None:
    """The bucket name goes into a URL path; a malformed one is a request to somewhere else.

    GCS names are constrained (lowercase, dots and dashes, 3–63 characters), and a value
    outside that set either 404s at a stranger's bucket or escapes the path entirely.
    """
    from korpus.infrastructure.gcs import GcsJsonClient

    for hostile in ("", "A", "korpus objects", "korpus/objects", "../other", "x" * 300):
        with pytest.raises(ValueError, match="invalid GCS configuration"):
            GcsJsonClient(hostile)


def test_a_healthcheck_against_a_different_bucket_fails(monkeypatch) -> None:
    """The metadata call must confirm it reached the bucket this store is bound to.

    A redirected or misconfigured endpoint answers happily about some other bucket, and a
    health check that only asks "did the call succeed" reports ready for a store the
    deployment does not own.
    """
    from korpus.infrastructure.gcs import GcsObjectStore

    class Metadata:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def bucket_metadata(self) -> dict[str, Any]:
            return self.payload

        def close(self) -> None:
            pass

    store = GcsObjectStore(bucket="korpus-objects", gcs=Metadata({"name": "somebody-else"}))  # type: ignore[arg-type]
    assert store.healthcheck() is False

    ok = GcsObjectStore(bucket="korpus-objects", gcs=Metadata({"name": "korpus-objects"}))  # type: ignore[arg-type]
    assert ok.healthcheck() is True


def test_a_retention_policy_shorter_than_required_fails_the_healthcheck() -> None:
    """Retention is the property that makes the store append-only in practice.

    A bucket whose lock is shorter than the declared requirement can have objects deleted
    inside the window the system promises they are kept, so reporting it healthy would
    assert a guarantee the bucket does not provide.
    """
    from korpus.infrastructure.gcs import GcsObjectStore

    class Retained:
        def __init__(self, period: int) -> None:
            self.period = period

        def bucket_metadata(self) -> dict[str, Any]:
            return {
                "name": "korpus-objects",
                "retentionPolicy": {"retentionPeriod": str(self.period)},
            }

        def close(self) -> None:
            pass

    required = 3600
    assert (
        GcsObjectStore(
            bucket="korpus-objects", retention_seconds=required, gcs=Retained(required - 1)  # type: ignore[arg-type]
        ).healthcheck()
        is False
    )
    assert (
        GcsObjectStore(
            bucket="korpus-objects", retention_seconds=required, gcs=Retained(required)  # type: ignore[arg-type]
        ).healthcheck()
        is True
    )
