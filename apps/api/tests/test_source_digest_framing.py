"""Preserve the published digest format across live, committed, and packaged bytes."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from korpus.application.provenance import (
    ProvenanceError,
    compute_source_digest,
    digest_source_records,
    evidence_source_path_included,
)

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.manifest_paths import source_included  # noqa: E402
from scripts.verify_package import verify  # noqa: E402

from .package_fixtures import SOURCE, manifest, package_files, record, write_package  # noqa: E402


@pytest.mark.parametrize(
    ("records", "expected"),
    [
        ([], "4c8bb8cb7bf264250de6f23c19fc5ee71625fe3c959c1ae31527b06bcfea2dc9"),
        (
            [("scripts/payload.bin", b"\x00\xff\n\x00")],
            "6c9bef8423566bc30b677f703b195034ec23b0989b01df9478656ae07416847d",
        ),
        (
            [("scripts/empty", b""), ("scripts/слід.py", b"value=1\n")],
            "75b3a91d2feae3434299682dc8cb6e8f41f1f0ff9e1853e4a54bdc13042532ba",
        ),
    ],
    ids=("empty", "binary", "unicode-and-empty"),
)
def test_live_and_record_digests_preserve_published_vectors(tmp_path, records, expected):
    for name, body in records:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    assert compute_source_digest(tmp_path) == expected
    assert digest_source_records(iter(records)) == expected


@pytest.mark.parametrize("size", [0, 1, 1024 * 1024 - 1, 1024 * 1024, 1024 * 1024 + 1, 2097157])
def test_live_digest_streams_large_members_in_bounded_reads(tmp_path, monkeypatch, size):
    target = tmp_path / "scripts/large.bin"
    target.parent.mkdir()
    body = (b"public-binary-control\x00\xff" * (size // 22 + 1))[:size]
    assert len(body) == size
    target.write_bytes(body)
    original = Path.open
    reads, handles = [], []

    class Reader:
        def __init__(self, handle):
            self.handle = handle

        def read(self, count=-1):
            assert 0 < count <= 1024 * 1024
            reads.append(count)
            return self.handle.read(count)

    @contextmanager
    def tracked_open(path, *args, **kwargs):
        with original(path, *args, **kwargs) as handle:
            if path == target:
                handles.append(handle)
                yield Reader(handle)
            else:
                yield handle

    monkeypatch.setattr(Path, "open", tracked_open)
    assert compute_source_digest(tmp_path) == digest_source_records([("scripts/large.bin", body)])
    assert reads and all(handle.closed for handle in handles)


@pytest.mark.parametrize("change", ["grow", "shrink"])
def test_live_digest_refuses_size_change_and_closes_the_member(tmp_path, monkeypatch, change):
    target = tmp_path / "scripts/changing.bin"
    target.parent.mkdir()
    target.write_bytes(b"neutral" * 400000)
    original = Path.open
    handles, changed = [], []

    class Reader:
        def __init__(self, handle):
            self.handle = handle

        def read(self, count=-1):
            value = self.handle.read(count)
            if not changed:
                with original(target, "ab" if change == "grow" else "r+b") as writer:
                    if change == "grow":
                        writer.write(b"additional neutral source bytes")
                    else:
                        writer.truncate(1024 * 1024 + 13)
                changed.append(True)
            return value

    @contextmanager
    def tracked_open(path, *args, **kwargs):
        with original(path, *args, **kwargs) as handle:
            if path == target:
                handles.append(handle)
                yield Reader(handle)
            else:
                yield handle

    monkeypatch.setattr(Path, "open", tracked_open)
    with pytest.raises(ProvenanceError, match="source changed while hashing"):
        compute_source_digest(tmp_path)
    assert changed == [True] and handles and all(handle.closed for handle in handles)


@pytest.mark.parametrize("path", ["Makefile", ".github/workflows/assurance.yml"])
def test_orchestration_mutation_changes_live_and_record_evidence_identity(tmp_path, path):
    records = {
        "Makefile": b"mutation:\n\tpython scripts/run_mutation_tests.py --jobs 1\n",
        ".github/workflows/assurance.yml": b"name: assurance\nenv:\n  KORPUS_MODE: baseline\n",
        "docs/README.md": b"Human documentation.\n",
    }
    for name, body in records.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    committed = [
        (name, body)
        for name, body in sorted(records.items())
        if evidence_source_path_included(name)
    ]
    before = compute_source_digest(tmp_path)
    assert before == digest_source_records(committed)
    changed = records[path] + b"# changed execution contract\n"
    (tmp_path / path).write_bytes(changed)
    after = compute_source_digest(tmp_path)
    assert after != before
    assert after == digest_source_records(
        [(name, changed if name == path else body) for name, body in committed]
    )
    (tmp_path / path).write_bytes(records[path])
    (tmp_path / "docs/README.md").write_bytes(b"Rewritten human documentation.\n")
    assert compute_source_digest(tmp_path) == before


@pytest.mark.parametrize("path", ["Makefile", ".github/workflows/assurance.yml"])
def test_packaged_orchestration_edit_cannot_reuse_old_research_evidence(tmp_path, path):
    files = package_files({path: b"neutral execution contract\n"})
    baseline = tmp_path / "baseline.zip"
    count = write_package(baseline, files)
    assert verify(baseline) == ([], count)
    files[path] += b"changed execution contract\n"
    # Inventory coherence cannot confer authority on stale research evidence.
    files[SOURCE] = manifest(
        [record(name, body) for name, body in sorted(files.items()) if source_included(Path(name))],
        "source",
    )
    poisoned = tmp_path / "poisoned.zip"
    write_package(poisoned, files)
    failures, _ = verify(poisoned)
    assert "assurance evidence source digest does not match packaged source" in failures
