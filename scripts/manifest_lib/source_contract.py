"""Strict source-manifest parser; only canonical, exact file records are admissible."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from korpus.application.final_release_evidence import strict_signed_json_object
from manifest_paths import source_included

_MANIFEST_FIELDS = frozenset(
    {"schema", "kind", "manifest_self_excluded", "file_count", "root_sha256", "files"}
)
_RECORD_FIELDS = frozenset({"path", "bytes", "sha256", "mode"})


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _valid_record(record: object) -> bool:
    if not isinstance(record, dict) or set(record) != _RECORD_FIELDS:
        return False
    name = record.get("path")
    if not isinstance(name, str) or not name or chr(92) in name:
        return False
    normalized = PurePosixPath(name)
    if (
        normalized.is_absolute()
        or ".." in normalized.parts
        or normalized.as_posix() != name
        or not source_included(Path(name))
    ):
        return False
    return (
        type(record.get("bytes")) is int
        and record["bytes"] >= 0
        and _sha256(record.get("sha256"))
        and record.get("mode") in {"0644", "0755"}
    )


def load_source_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse with duplicate-key refusal, exact fields, typed counts and unique paths."""
    manifest = dict(strict_signed_json_object(path.read_bytes(), "source manifest"))
    if manifest.get("schema") != "korpus.source-manifest.v2" or manifest.get("kind") != "source":
        raise ValueError("invalid source manifest schema")
    records = manifest.get("files")
    if not isinstance(records, list):
        raise ValueError("invalid source manifest records")
    if set(manifest) != _MANIFEST_FIELDS or manifest.get("manifest_self_excluded") is not True:
        raise ValueError("invalid source manifest header fields")
    if type(manifest.get("file_count")) is not int or manifest["file_count"] != len(records):
        raise ValueError("invalid source manifest file count")
    if not _sha256(manifest.get("root_sha256")):
        raise ValueError("invalid source manifest root digest")
    if not all(_valid_record(record) for record in records):
        raise ValueError("invalid source manifest file record")
    paths = [record["path"] for record in records]
    if len(paths) != len(set(paths)) or paths != sorted(paths):
        raise ValueError("duplicate or unsorted source manifest file records")
    return manifest, records
