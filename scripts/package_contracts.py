"""Semantic contracts that the extracted release package must satisfy."""
from __future__ import annotations

import json
from pathlib import Path

from assurance_snapshot_verification import verify_assurance_snapshot
from manifest_lib.source_manifest import verify_source_manifest

RELEASE_IDENTITY_PATH = "apps/api/src/korpus/release.json"


def _packaged_release(root: Path) -> str:
    path = root / RELEASE_IDENTITY_PATH
    if not path.is_file():
        raise RuntimeError("packaged release identity is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("packaged release identity is unreadable or invalid JSON") from error
    if not isinstance(payload, dict) or payload.get("schema") != "korpus.release-identity.v1":
        raise RuntimeError("invalid packaged release identity schema")
    release = payload.get("tag")
    if not isinstance(release, str) or not release:
        raise RuntimeError("packaged release identity has no tag")
    return release


def verify_package_contracts(root: Path, modes: dict[str, str]) -> list[str]:
    failures, _ = verify_source_manifest(root, modes)
    try:
        release = _packaged_release(root)
    except RuntimeError as error:
        failures.append(str(error))
        return failures
    failures.extend(verify_assurance_snapshot(root, release))
    return failures
