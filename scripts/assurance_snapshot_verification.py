"""Verify canonical research-assurance snapshot structure against exact report bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from assurance_snapshot_contract import canonical_snapshot_records

SNAPSHOT_PATH = "reports/ASSURANCE_SNAPSHOT.json"


def verify_assurance_snapshot(root: Path, expected_release: str) -> list[str]:
    snapshot_path = root / SNAPSHOT_PATH
    if not snapshot_path.is_file():
        return ["assurance snapshot is missing"]
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["assurance snapshot is unreadable or invalid JSON"]

    structure_failures, records = canonical_snapshot_records(snapshot, expected_release)
    failures = list(structure_failures)
    for record in records:
        path = root / str(record["path"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if (
            not path.is_file()
            or path.stat().st_size != record.get("bytes")
            or digest != record.get("sha256")
        ):
            failures.append(f"snapshot record mismatch: {record.get('path')}")
    return failures
