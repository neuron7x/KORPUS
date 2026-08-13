"""Semantic contracts that the extracted release package must satisfy."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_SRC = SCRIPT_DIR.parent / "apps/api/src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from korpus.application.provenance import compute_source_digest  # noqa: E402
from manifest_lib.source_manifest import verify_source_manifest  # noqa: E402
from research_assurance_verification import verify_research_assurance  # noqa: E402
from source_digest import source_tree_digest  # noqa: E402

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
    if failures:
        return failures
    try:
        release = _packaged_release(root)
        full_digest = source_tree_digest(root=root)
    except RuntimeError as error:
        return [str(error)]
    evidence_digest = compute_source_digest(root)
    return verify_research_assurance(
        root,
        release,
        source_tree_sha256=full_digest,
        evidence_source_sha256=evidence_digest,
        binding="packaged source",
    )
