"""The compiler archive is authenticated before parsing or changing any destination."""

from __future__ import annotations

import hashlib
import io
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import install_scanner_compiler as installer  # noqa: E402


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as stream:
        for name, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.mode = 0o755
            if kind == tarfile.REGTYPE:
                member.size = 7
            else:
                member.linkname = "outside"
            stream.addfile(member, io.BytesIO(b"neutral") if member.isfile() else None)
    return output.getvalue()


def pin_fixture(monkeypatch, raw):
    monkeypatch.setattr(installer, "GO_ARCHIVE_SHA256", hashlib.sha256(raw).hexdigest())


def test_changed_archive_is_refused_before_parsing_or_destination_creation(tmp_path):
    destination = tmp_path / "compiler"
    with pytest.raises(ValueError, match="archive digest"):
        installer.install(b"changed compiler archive", destination)
    assert not destination.exists()


def test_install_uses_a_fresh_destination_and_preserves_executable_mode(tmp_path, monkeypatch):
    raw = archive([("go/bin/go", tarfile.REGTYPE)])
    pin_fixture(monkeypatch, raw)
    destination = tmp_path / "compiler"
    root = installer.install(raw, destination)
    assert (root / "bin/go").read_bytes() == b"neutral"
    assert (root / "bin/go").stat().st_mode & 0o111 == 0o111
    with pytest.raises(ValueError, match="already exists"):
        installer.install(raw, destination)
    assert (root / "bin/go").read_bytes() == b"neutral"


@pytest.mark.parametrize(
    "entries",
    [
        [("../outside", tarfile.REGTYPE)],
        [("/absolute", tarfile.REGTYPE)],
        [("go/../../outside", tarfile.REGTYPE)],
        [("foreign/bin/go", tarfile.REGTYPE)],
        [("go/link", tarfile.SYMTYPE)],
        [("go/link", tarfile.LNKTYPE)],
        [("go/fifo", tarfile.FIFOTYPE)],
        [("go/bin/go", tarfile.REGTYPE), ("go/bin/./go", tarfile.REGTYPE)],
    ],
    ids=(
        "parent",
        "absolute",
        "nested-parent",
        "foreign-root",
        "symlink",
        "hardlink",
        "fifo",
        "alias",
    ),
)
def test_noncanonical_archive_is_refused_before_extraction(tmp_path, monkeypatch, entries):
    raw = archive(entries)
    pin_fixture(monkeypatch, raw)
    with pytest.raises(ValueError, match="unique regular input"):
        installer.install(raw, tmp_path / "compiler")
    assert list(tmp_path.iterdir()) == []


def test_expanded_budget_refuses_before_extraction(tmp_path, monkeypatch):
    raw = archive([("go/bin/go", tarfile.REGTYPE)])
    pin_fixture(monkeypatch, raw)
    monkeypatch.setattr(installer, "MAX_EXPANDED", 6)
    with pytest.raises(ValueError, match="expanded size"):
        installer.install(raw, tmp_path / "compiler")
    assert list(tmp_path.iterdir()) == []


def test_existing_symlink_is_never_used_as_a_destination(tmp_path, monkeypatch):
    raw = archive([("go/bin/go", tarfile.REGTYPE)])
    pin_fixture(monkeypatch, raw)
    destination = tmp_path / "compiler"
    destination.symlink_to(tmp_path / "absent")
    with pytest.raises(ValueError, match="already exists"):
        installer.install(raw, destination)
    assert not (tmp_path / "absent").exists()
