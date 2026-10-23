"""Issue #91: extraction must not partially mutate a caller destination."""

from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path

import pytest

from scripts import archive_atomic_publish
from scripts.safe_archive_extract import extract_safe_archive
from scripts.zip_safety import safety_failures


def _archive(path: Path, *members: tuple[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)


@pytest.mark.parametrize("existing", [False, True])
def test_valid_archive_publishes_to_absent_or_empty_destination(
    tmp_path: Path, existing: bool
) -> None:
    archive, dest = tmp_path / "release.zip", tmp_path / "target"
    _archive(archive, ("payload.txt", b"safe"))
    if existing:
        dest.mkdir(mode=0o750)
    first = extract_safe_archive(archive, dest)
    assert first == dest / "payload.txt"
    assert first.read_bytes() == b"safe"
    if existing and os.name == "posix":
        assert stat.S_IMODE(dest.stat().st_mode) == 0o750
    assert not list(tmp_path.glob(".target.staging-*"))


@pytest.mark.parametrize(
    "bad_name",
    ["x" * 256, "é" * 128, "/".join(["p" * 220] * 20)],
)
def test_length_admission_rejects_before_destination_write(tmp_path: Path, bad_name: str) -> None:
    archive, dest = tmp_path / "bad.zip", tmp_path / "target"
    _archive(archive, ("ok.txt", b"first"), (bad_name, b"second"))
    with zipfile.ZipFile(archive) as zf:
        assert any("UTF-8 bytes" in reason for reason in safety_failures(zf))
    with pytest.raises(RuntimeError, match="unsafe release ZIP"):
        extract_safe_archive(archive, dest)
    assert not dest.exists()
    assert not list(tmp_path.glob(".target.staging-*"))


@pytest.mark.parametrize("existing", [False, True])
def test_mid_extraction_failure_leaves_destination_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    archive, dest = tmp_path / "fault.zip", tmp_path / "target"
    _archive(archive, ("ok.txt", b"first"), ("second.txt", b"second"))
    if existing:
        dest.mkdir()

    def fail_midstream(self, path, *args, **kwargs):
        (Path(path) / "ok.txt").write_bytes(b"partial")
        raise OSError("simulated disk failure after first member")

    monkeypatch.setattr(zipfile.ZipFile, "extractall", fail_midstream)
    with pytest.raises(OSError, match="simulated disk failure"):
        extract_safe_archive(archive, dest)
    assert dest.exists() is existing
    if existing:
        assert list(dest.iterdir()) == []
    assert not list(tmp_path.glob(".target.staging-*"))


def test_nonempty_destination_is_never_overwritten(tmp_path: Path) -> None:
    archive, dest = tmp_path / "good.zip", tmp_path / "target"
    _archive(archive, ("sentinel", b"replacement"))
    dest.mkdir()
    (dest / "sentinel").write_bytes(b"original")
    with pytest.raises(FileExistsError, match="absent or empty"):
        extract_safe_archive(archive, dest)
    assert (dest / "sentinel").read_bytes() == b"original"


def test_failed_atomic_publish_preserves_existing_empty_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, dest = tmp_path / "valid.zip", tmp_path / "target"
    _archive(archive, ("payload.txt", b"safe"))
    dest.mkdir()

    def refuse_rename(*_args):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(archive_atomic_publish.os, "replace", refuse_rename)
    with pytest.raises(OSError, match="simulated rename failure"):
        extract_safe_archive(archive, dest)
    assert dest.is_dir() and list(dest.iterdir()) == []
    assert not list(tmp_path.glob(".target.staging-*"))
