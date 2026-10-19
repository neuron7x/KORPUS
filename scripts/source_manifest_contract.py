from __future__ import annotations

import json
from pathlib import Path

from manifest_lib.integrity import manifest_failures, mode_string, record_failures
from manifest_paths import source_paths


def _path_failures(
    records: list[object], authoritative: list[str]
) -> tuple[dict[str, object], list[str]]:
    paths = [str(record.get("path")) for record in records if isinstance(record, dict)]
    by_path: dict[str, object] = {
        str(record.get("path")): record for record in records if isinstance(record, dict)
    }
    duplicates = sorted({path for path in paths if paths.count(path) > 1})
    failures = [f"duplicate manifest paths: {duplicates}"] if duplicates else []
    if len(records) != len(authoritative):
        failures.append(
            f"record count mismatch manifest={len(records)} authoritative={len(authoritative)}"
        )
    if sorted(by_path) != authoritative:
        failures.append(
            "path parity mismatch "
            f"in_tree_not_in_manifest={sorted(set(authoritative) - set(by_path))} "
            f"in_manifest_not_in_tree={sorted(set(by_path) - set(authoritative))}"
        )
    return by_path, failures


def verify_source_manifest(root: Path) -> dict[str, object]:
    path = root / "SOURCE_MANIFEST.json"
    if not path.is_file():
        return {"valid": False, "failures": ["SOURCE_MANIFEST.json is missing"]}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"valid": False, "failures": ["SOURCE_MANIFEST.json is not valid JSON"]}
    if not isinstance(manifest, dict):
        return {"valid": False, "failures": ["invalid source manifest object"]}
    if manifest.get("schema") != "korpus.source-manifest.v2" or manifest.get("kind") != "source":
        return {"valid": False, "failures": ["invalid source manifest schema"]}
    records = manifest.get("files")
    if not isinstance(records, list):
        return {"valid": False, "failures": ["invalid source manifest records"]}
    authoritative = [path.as_posix() for path in source_paths(root)]
    by_path, failures = _path_failures(records, authoritative)
    failures = [*manifest_failures(manifest, records), *failures]
    for relative in authoritative:
        file, record = root / relative, by_path.get(relative)
        if not file.is_file():
            failures.append(f"missing source file: {relative}")
        elif isinstance(record, dict):
            failures.extend(
                f"source {item}"
                for item in record_failures(file, record, mode_string(file, source=True))
            )
    return {
        "valid": not failures,
        "files": len(authoritative),
        "root_sha256": manifest.get("root_sha256"),
        "failures": failures,
    }
