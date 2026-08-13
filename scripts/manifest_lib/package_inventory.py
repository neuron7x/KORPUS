from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from manifest_lib.integrity import manifest_failures

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def canonical_member_name(name: str, *, directory: bool = False) -> str | None:
    """Return one canonical relative POSIX name, or None for an ambiguous/unsafe name."""
    candidate = name[:-1] if directory and name.endswith("/") else name
    if not candidate or candidate.startswith("/") or _DRIVE_PREFIX.match(candidate):
        return None
    if "\\" in candidate:
        return None
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    canonical = "/".join(parts)
    if canonical != candidate:
        return None
    return canonical


def archive_inventory_failures(archive: zipfile.ZipFile) -> list[str]:
    """Reject archive ambiguity before any member reaches filesystem extraction."""
    failures: list[str] = []
    seen: dict[str, str] = {}
    for info in archive.infolist():
        canonical = canonical_member_name(info.filename, directory=info.is_dir())
        if canonical is None:
            failures.append(f"non-canonical archive member: {info.filename!r}")
            continue
        prior = seen.get(canonical)
        if prior is not None:
            failures.append(
                f"duplicate archive member: {canonical!r} ({prior!r}, {info.filename!r})"
            )
            continue
        seen[canonical] = info.filename
    return failures


def load_distribution_records(
    root: Path,
) -> tuple[list[str], dict[str, dict[str, object]]]:
    """Load one aggregate-valid record per canonical distribution path."""
    path = root / "DISTRIBUTION_MANIFEST.json"
    if not path.is_file():
        raise RuntimeError("DISTRIBUTION_MANIFEST.json missing from archive")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("DISTRIBUTION_MANIFEST.json is unreadable or invalid JSON") from error
    if not isinstance(manifest, dict):
        return ["invalid distribution manifest object"], {}

    failures: list[str] = []
    if manifest.get("schema") != "korpus.distribution-manifest.v2":
        failures.append("invalid distribution manifest schema")
    records = manifest.get("files")
    if not isinstance(records, list):
        return [*failures, "invalid distribution manifest records"], {}

    by_path: dict[str, dict[str, object]] = {}
    structured_records: list[dict[str, object]] = []
    for record in records:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("path"), str)
            or not isinstance(record.get("mode"), str)
            or not isinstance(record.get("sha256"), str)
            or not isinstance(record.get("bytes"), int)
        ):
            failures.append("invalid distribution manifest record")
            continue
        relative = str(record["path"])
        if canonical_member_name(relative) != relative:
            failures.append(f"non-canonical distribution record path: {relative!r}")
            continue
        if relative in by_path:
            failures.append(f"duplicate distribution manifest record: {relative}")
            continue
        by_path[relative] = record
        structured_records.append(record)

    if len(structured_records) == len(records):
        failures.extend(manifest_failures(manifest, structured_records))
    return failures, by_path
