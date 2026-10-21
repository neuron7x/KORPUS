"""Bounded offline controls for PR #88's catalog file descriptor boundary."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import kb_reference_admission as gate


def _payload(index: int = 0) -> bytes:
    row = {
        "source_id": f"SRC_TEST_{index}",
        "title": "Reference metadata",
        "publisher": "Example publisher",
        "url": f"https://example.org/reference/{index}",
        "category_ids": ["T07_DATA_PROVENANCE_AND_RIGHTS"],
        "access_model": "PUBLIC_LANDING",
        "reuse_status": "UNASSESSED",
        "integration_mode": "METADATA_ONLY",
    }
    return (json.dumps(row) + "\n").encode("utf-8")


def _catalog(tmp_path: Path, data: bytes | None = None) -> Path:
    path = tmp_path / "catalog.jsonl"
    path.write_bytes(_payload() if data is None else data)
    return path


def _assert_closed(result: dict[str, object], status: str) -> None:
    assert result["structure_status"] == status
    assert result["candidate_status"] == "BLOCKED"
    assert result["production_authorized"] is False
    assert result["network_access_performed"] is False
    assert result["indexable"] == result["rights_cleared"] == result["acquired"] == 0


def test_one_descriptor_uses_nofollow_and_nonblock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _catalog(tmp_path)
    real_open = os.open
    descriptors = []

    def checked_open(name: Path, flags: int) -> int:
        assert name == path
        assert flags & os.O_NOFOLLOW
        assert flags & os.O_NONBLOCK
        descriptor = real_open(name, flags)
        descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(gate.os, "open", checked_open)
    _assert_closed(gate.verify_catalog(path), "PASS")
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_reader_never_reopens_path_as_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _catalog(tmp_path)

    def forbidden_read(*args: object, **kwargs: object) -> str:
        raise OSError("unbounded path-based text read is forbidden")

    monkeypatch.setattr(Path, "read_text", forbidden_read)
    _assert_closed(gate.verify_catalog(path), "PASS")


@pytest.mark.parametrize("extra,status", [(0, "PASS"), (1, "FAIL")])
def test_exact_byte_limit(tmp_path: Path, extra: int, status: str) -> None:
    payload = _payload()
    path = _catalog(tmp_path, payload + b" " * (gate.MAX_BYTES - len(payload) + extra))
    _assert_closed(gate.verify_catalog(path), status)


@pytest.mark.parametrize("kind", ["empty", "invalid_utf8", "directory", "missing"])
def test_invalid_file_is_structured_failure(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "catalog.jsonl"
    if kind == "empty":
        path.write_bytes(b"")
    elif kind == "invalid_utf8":
        path.write_bytes(b"\xff\xfe")
    elif kind == "directory":
        path.mkdir()
    result = gate.verify_catalog(path)
    _assert_closed(result, "FAIL")
    assert result["errors"]


@pytest.mark.parametrize("broken", [False, True])
def test_final_symlink_is_refused(tmp_path: Path, broken: bool) -> None:
    target = tmp_path / "missing" if broken else _catalog(tmp_path)
    link = tmp_path / "link.jsonl"
    link.symlink_to(target)
    _assert_closed(gate.verify_catalog(link), "FAIL")


def test_fifo_refused_without_waiting_for_a_writer(tmp_path: Path) -> None:
    path = tmp_path / "fifo.jsonl"
    os.mkfifo(path)
    result = subprocess.run(
        [sys.executable, str(Path(gate.__file__).resolve()), "--catalog", str(path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2
    _assert_closed(json.loads(result.stdout), "FAIL")
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("flag", ["O_NOFOLLOW", "O_NONBLOCK"])
def test_missing_safety_primitive_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    path = _catalog(tmp_path)
    monkeypatch.delattr(gate.os, flag)
    result = gate.verify_catalog(path)
    _assert_closed(result, "FAIL")
    assert "unsupported" in str(result["errors"])


def test_open_error_is_structured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _catalog(tmp_path)

    def denied(*args: object, **kwargs: object) -> int:
        raise PermissionError("catalog denied")

    monkeypatch.setattr(gate.os, "open", denied)
    _assert_closed(gate.verify_catalog(path), "FAIL")


def test_read_is_bounded_even_when_stat_understates_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _catalog(tmp_path)
    requested = []
    payload = _payload() + b" " * gate.MAX_BYTES

    class ObservedReader(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            requested.append(size)
            assert size == gate.MAX_BYTES + 1
            return super().read(size)

    monkeypatch.setattr(gate.os, "fdopen", lambda *args, **kwargs: ObservedReader(payload))
    result = gate.verify_catalog(path)
    _assert_closed(result, "FAIL")
    assert requested == [gate.MAX_BYTES + 1]
    assert "byte maximum" in str(result["errors"])


@pytest.mark.parametrize("field", ["st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"])
def test_detectable_change_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    path = _catalog(tmp_path)
    real_fstat = os.fstat
    calls = 0

    def changed(descriptor: int) -> SimpleNamespace:
        nonlocal calls
        actual = real_fstat(descriptor)
        names = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        attributes = {name: getattr(actual, name) for name in names}
        calls += 1
        if calls == 2:
            attributes[field] += 1
        return SimpleNamespace(**attributes)

    monkeypatch.setattr(gate.os, "fstat", changed)
    result = gate.verify_catalog(path)
    _assert_closed(result, "FAIL")
    assert "changed" in str(result["errors"])


def test_short_read_is_not_accepted_as_a_complete_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _payload()
    path = _catalog(tmp_path, payload + b" " * 16)
    monkeypatch.setattr(gate.os, "fdopen", lambda *args, **kwargs: io.BytesIO(payload))
    result = gate.verify_catalog(path)
    _assert_closed(result, "FAIL")
    assert "changed" in str(result["errors"])


def test_descriptor_closed_after_read_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _catalog(tmp_path)
    real_open = os.open
    descriptors = []

    def observed_open(name: Path, flags: int) -> int:
        descriptor = real_open(name, flags)
        descriptors.append(descriptor)
        return descriptor

    class FailingReader(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise OSError("controlled read failure")

    monkeypatch.setattr(gate.os, "open", observed_open)
    monkeypatch.setattr(gate.os, "fdopen", lambda *args, **kwargs: FailingReader())
    _assert_closed(gate.verify_catalog(path), "FAIL")
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


@pytest.mark.parametrize("count,status", [(256, "PASS"), (257, "FAIL")])
def test_record_limit_is_unchanged(tmp_path: Path, count: int, status: str) -> None:
    path = _catalog(tmp_path, b"".join(_payload(index) for index in range(count)))
    assert path.stat().st_size < gate.MAX_BYTES
    _assert_closed(gate.verify_catalog(path), status)


def test_cli_works_outside_repository_without_pythonpath(tmp_path: Path) -> None:
    path = _catalog(tmp_path)
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(Path(gate.__file__).resolve()), "--catalog", str(path)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    _assert_closed(json.loads(result.stdout), "PASS")
