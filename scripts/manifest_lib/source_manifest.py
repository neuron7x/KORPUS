from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from manifest_lib.integrity import manifest_failures, mode_string, record_failures
from manifest_paths import source_paths

SOURCE_SCHEMA = "korpus.source-manifest.v2"


def _record_index(
    records: list[object],
) -> tuple[list[str], dict[str, dict[str, object]]]:
    failures: list[str] = []
    by_path: dict[str, dict[str, object]] = {}
    for record in records:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("path"), str)
            or not isinstance(record.get("mode"), str)
            or not isinstance(record.get("sha256"), str)
        ):
            failures.append("invalid source manifest record")
            continue
        path = str(record["path"])
        if path in by_path:
            failures.append(f"duplicate source manifest record: {path}")
            continue
        by_path[path] = record
    return failures, by_path


def verify_source_manifest(
    root: Path, archive_modes: Mapping[str, str] | None = None
) -> tuple[list[str], dict[str, object]]:
    """Verify an embedded source manifest against the exact source files under root."""
    manifest_path = root / "SOURCE_MANIFEST.json"
    if not manifest_path.is_file():
        return ["SOURCE_MANIFEST.json is missing"], {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["SOURCE_MANIFEST.json is unreadable or invalid JSON"], {}
    if not isinstance(manifest, dict):
        return ["invalid source manifest object"], {}

    failures: list[str] = []
    if manifest.get("schema") != SOURCE_SCHEMA or manifest.get("kind") != "source":
        failures.append("invalid source manifest schema")
    records = manifest.get("files")
    if not isinstance(records, list):
        return [*failures, "invalid source manifest records"], {}

    record_structure_failures, by_path = _record_index(records)
    failures.extend(record_structure_failures)
    if not record_structure_failures:
        failures.extend(manifest_failures(manifest, records))

    authoritative = [path.as_posix() for path in source_paths(root)]
    if sorted(by_path) != authoritative:
        missing = sorted(set(authoritative) - set(by_path))
        extra = sorted(set(by_path) - set(authoritative))
        failures.append(f"path parity mismatch missing={missing} extra={extra}")

    for relative in authoritative:
        path = root / relative
        record = by_path.get(relative, {})
        if not path.is_file():
            failures.append(f"missing source file: {relative}")
            continue
        actual_mode = (
            archive_modes.get(relative)
            if archive_modes is not None
            else mode_string(path, source=True)
        )
        for failure in record_failures(path, record, actual_mode):
            failures.append(f"source {failure}")

    summary = {"files": len(authoritative), "root_sha256": manifest.get("root_sha256")}
    return failures, summary
