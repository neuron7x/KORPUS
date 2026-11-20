"""Actual native log controls plus bounded malformed and partial log witnesses."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import source_security_native as native
from scripts.source_security_contract import validate_outputs

from .source_security_fixtures import native_log, output_bytes, write_locks


@pytest.mark.parametrize(
    ("commits", "byte_count", "valid"),
    [
        pytest.param(0, 1, False, id="zero-commits"),
        pytest.param(1, 0, False, id="zero-bytes"),
        pytest.param(0, 0, False, id="zero-both"),
        pytest.param(1, 1, True, id="minimum-positive"),
    ],
)
def test_reported_native_census_requires_both_positive_counts(
    commits: int, byte_count: int, valid: bool
) -> None:
    # A modeled frame tests reported counts, not actual input consumption or EOF.
    raw = (
        f"12:53AM INF {commits} commits scanned.\n"
        f"12:53AM INF scanned ~{byte_count} bytes (0 MB) in 0s\n"
        "12:53AM INF no leaks found\n"
    ).encode()
    if valid:
        native.validate_gitleaks_log(raw)
    else:
        with pytest.raises(ValueError, match="complete success summary"):
            native.validate_gitleaks_log(raw)


@pytest.mark.parametrize("field", ["commits", "bytes"])
@pytest.mark.parametrize("count", ["00", "01", "-1", "+1", "1.0", "١", "１"])
def test_native_census_rejects_noncanonical_decimal_counts(field: str, count: str) -> None:
    commits, byte_count = (count, "1") if field == "commits" else ("1", count)
    raw = (
        f"12:53AM INF {commits} commits scanned.\n"
        f"12:53AM INF scanned ~{byte_count} bytes (0 MB) in 0s\n"
        "12:53AM INF no leaks found\n"
    ).encode()
    with pytest.raises(ValueError, match="complete success summary"):
        native.validate_gitleaks_log(raw)


@pytest.mark.parametrize("name", ["clean_stdlib", "clean_release"])
def test_original_complete_native_log_bytes_are_accepted_without_rewriting(
    tmp_path: Path, name: str
) -> None:
    write_locks(tmp_path)
    raw = native_log(name)
    path = tmp_path / "gitleaks.log"
    path.write_bytes(raw)
    captured = native.read_native_log(path)
    assert captured == raw
    members = output_bytes()
    members["gitleaks.log"] = captured
    validate_outputs(members, tmp_path)
    assert members["gitleaks.log"] == path.read_bytes() == raw


@pytest.mark.parametrize("name", ["damaged_stdlib", "damaged_release"])
def test_original_native_zero_exit_input_errors_are_refused(tmp_path: Path, name: str) -> None:
    write_locks(tmp_path)
    members = output_bytes()
    members["gitleaks.log"] = native_log(name)
    assert members["gitleaks.json"] == b"[]"
    with pytest.raises(ValueError, match="input error"):
        validate_outputs(members, tmp_path)


@pytest.mark.parametrize(
    "message",
    [
        "ERR [git] fatal: unable to read neutral-object",
        "FTL neutral failure",
        "PNC neutral panic",
        "WRN command aborted",
        "WRN error reading neutral-object",
        "WRN bad object neutral-object",
        "WRN unable to read neutral-object",
        "WRN fatal: neutral failure",
        "WRN panic: neutral failure",
        "WRN context deadline exceeded",
        "WRN timeout reached",
        "WRN partial scan completed",
        "WRN no leaks found in partial scan",
        "SOURCE_SECURITY_TIMEOUT",
        "SOURCE_SECURITY_EXECUTION_UNAVAILABLE",
        "SOURCE_SECURITY_CLEANUP_UNPROVEN",
        "\x1b[31mERR\x1b[0m neutral failure",
    ],
)
def test_complete_summary_cannot_hide_an_explicit_error(message: str) -> None:
    # This is an explicitly modeled extra line; the surrounding success frame is native.
    raw = ("12:08AM " + message + "\n").encode() + native_log("clean_release")
    with pytest.raises(ValueError, match="input error"):
        native.validate_gitleaks_log(raw)


def test_benign_warning_does_not_replace_or_invalidate_a_complete_native_summary() -> None:
    raw = b"12:08AM WRN neutral optional metadata unavailable\n" + native_log("clean_release")
    native.validate_gitleaks_log(raw)


@pytest.mark.parametrize(
    "poison",
    [
        "empty",
        "missing-commits",
        "missing-bytes",
        "missing-terminal",
        "duplicate-commits",
        "duplicate-bytes",
        "duplicate-terminal",
        "reordered",
        "extra-tail",
        "no-final-newline",
        "invalid-utf8",
        "json-string",
        "ansi-cursor",
        "ansi-incomplete",
        "nul",
        "carriage-return",
        "c1-control",
    ],
)
def test_missing_truncated_or_malformed_native_log_is_refused(poison: str) -> None:
    raw = native_log("clean_stdlib")
    lines = raw.splitlines(keepends=True)
    if poison == "empty":
        raw = b""
    elif poison.startswith("missing-"):
        removed = {"missing-commits": 0, "missing-bytes": 1, "missing-terminal": 2}[poison]
        raw = b"".join(line for index, line in enumerate(lines) if index != removed)
    elif poison.startswith("duplicate-"):
        added = {"duplicate-commits": 0, "duplicate-bytes": 1, "duplicate-terminal": 2}[poison]
        raw = lines[added] + raw
    elif poison == "reordered":
        raw = lines[1] + lines[0] + lines[2]
    elif poison == "extra-tail":
        raw += b"12:08AM INF neutral unexpected tail\n"
    elif poison == "no-final-newline":
        raw = raw[:-1]
    elif poison == "invalid-utf8":
        raw = b"\xff" + raw
    elif poison == "json-string":
        raw = json.dumps(raw.decode()).encode() + b"\n"
    else:
        raw = {
            "ansi-cursor": b"\x1b[2K",
            "ansi-incomplete": b"\x1b[31",
            "nul": b"\x00",
            "carriage-return": b"\r",
            "c1-control": "\u0085".encode(),
        }[poison] + raw
    with pytest.raises(ValueError):
        native.validate_gitleaks_log(raw)


def test_native_log_byte_limit_is_fixed_and_never_truncates_into_success(tmp_path: Path) -> None:
    assert native.MAX_GITLEAKS_LOG_BYTES == 16 * 1024 * 1024
    raw = native_log("clean_release")
    oversized = b" " * (native.MAX_GITLEAKS_LOG_BYTES + 1 - len(raw)) + raw
    with pytest.raises(ValueError, match="oversized"):
        native.validate_gitleaks_log(oversized)
    path = tmp_path / "oversized.log"
    with path.open("wb") as stream:
        stream.truncate(native.MAX_GITLEAKS_LOG_BYTES + 1)
    with pytest.raises(ValueError, match="oversized"):
        native.read_native_log(path)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_nonregular_native_log_is_refused_without_blocking(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "gitleaks.log"
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_bytes(native_log("clean_release"))
        path.symlink_to(target)
    else:
        os.mkfifo(path)
    with pytest.raises((OSError, ValueError)):
        native.read_native_log(path)


def test_native_log_changed_during_capture_is_refused(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "gitleaks.log"
    raw = native_log("clean_release")
    path.write_bytes(raw)
    monkeypatch.setattr(
        native.os,
        "fstat",
        lambda _fd: SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_size=len(raw) + 1),
    )
    with pytest.raises(ValueError, match="changed while reading"):
        native.read_native_log(path)
