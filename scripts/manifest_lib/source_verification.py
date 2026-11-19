"""Verify one strict source manifest against an independently admitted inventory."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from manifest_lib.integrity import manifest_failures, record_failures
from manifest_lib.source_contract import load_source_manifest
from path_admission import regular_file


def source_manifest_failures(
    root: Path, inventory: Mapping[str, str]
) -> tuple[list[str], str | None]:
    path = root / "SOURCE_MANIFEST.json"
    if not regular_file(path):
        return ["SOURCE_MANIFEST.json is missing or symlinked"], None
    try:
        manifest, records = load_source_manifest(path)
    except (OSError, ValueError) as error:
        return [str(error)], None
    by_path = {record["path"]: record for record in records}
    failures = manifest_failures(manifest, records)
    if sorted(by_path) != sorted(inventory):
        failures.append(
            "source path parity mismatch "
            f"in_tree_not_in_manifest={sorted(set(inventory) - set(by_path))} "
            f"in_manifest_not_in_tree={sorted(set(by_path) - set(inventory))}"
        )
    for relative, mode in inventory.items():
        file, record = root / relative, by_path.get(relative)
        if not regular_file(file):
            failures.append(f"missing or symlinked source file: {relative}")
        elif record is not None:
            failures.extend(f"source {item}" for item in record_failures(file, record, mode))
    return failures, str(manifest["root_sha256"])
