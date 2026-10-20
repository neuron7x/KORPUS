"""Deterministic bounds and mutation controls for single-fd artifact capture."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _admission():
    script = ROOT / "scripts/snapshot_admission.py"
    spec = importlib.util.spec_from_file_location("snapshot_admission_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bounded_snapshot_preserves_exact_sha(tmp_path: Path) -> None:
    archive = tmp_path / "artifact.zip"
    archive.write_bytes(b"normal captured bytes")
    with archive.open("rb") as source, tempfile.TemporaryFile(mode="w+b") as snapshot:
        digest = _admission().copy_bounded(source, snapshot)
        assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()
        assert snapshot.read() == archive.read_bytes()


def test_sparse_oversize_is_rejected_before_copy(tmp_path: Path) -> None:
    archive = tmp_path / "sparse.zip"
    with archive.open("wb") as output:
        output.truncate(_admission().MAX_ARCHIVE_BYTES + 1)
    with archive.open("rb") as source, tempfile.TemporaryFile(mode="w+b") as snapshot:
        with pytest.raises(RuntimeError, match="input budget exceeded"):
            _admission().copy_bounded(source, snapshot)
        assert snapshot.tell() == 0


@pytest.mark.parametrize("mutation", ["append", "truncate"])
def test_file_mutation_during_copy_is_rejected(tmp_path: Path, mutation: str) -> None:
    archive = tmp_path / "moving.zip"
    archive.write_bytes(b"abcdefgh")

    class MutatingSource:
        def __init__(self, opened):
            self.opened = opened
            self.once = False

        def fileno(self) -> int:
            return self.opened.fileno()

        def read(self, size: int) -> bytes:
            chunk = self.opened.read(size)
            if not self.once:
                self.once = True
                if mutation == "append":
                    with archive.open("ab") as writer:
                        writer.write(b"changed")
                else:
                    with archive.open("r+b") as writer:
                        writer.truncate(0)
            return chunk

    with archive.open("rb") as source, tempfile.TemporaryFile(mode="w+b") as snapshot:
        with pytest.raises(RuntimeError, match="archive changed during snapshot"):
            _admission().copy_bounded(MutatingSource(source), snapshot)


def test_nonregular_descriptor_is_rejected_before_read() -> None:
    read_fd, write_fd = os.pipe()
    try:
        with os.fdopen(read_fd, "rb") as source, tempfile.TemporaryFile(mode="w+b") as snap:
            with pytest.raises(RuntimeError, match="regular file"):
                _admission().copy_bounded(source, snap)
    finally:
        os.close(write_fd)
