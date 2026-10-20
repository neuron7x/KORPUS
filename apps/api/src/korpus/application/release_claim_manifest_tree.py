from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

from korpus.application.release_claim_git_tree import TreeFile, _working_paths
from scripts.manifest_lib.integrity import manifest_root
from scripts.manifest_paths import source_included


def _regular_file(root: Path, relative: Path) -> tuple[str, bytes] | None:
    target = root / relative
    try:
        metadata = target.lstat()
        if not stat.S_ISREG(metadata.st_mode) or target.resolve(strict=True) != (
            root.resolve() / relative
        ):
            return None
        content = target.read_bytes()
    except (OSError, RuntimeError):
        return None
    mode = "0755" if metadata.st_mode & 0o111 else "0644"
    return mode, content


def manifest_record(candidate: tuple[Path, object]) -> TreeFile | None:
    root, record = candidate
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        return None
    relative = Path(record["path"])
    if (
        relative.as_posix() != record["path"]
        or relative.is_absolute()
        or ".." in relative.parts
        or not source_included(relative)
    ):
        return None
    result = _regular_file(root, relative)
    if result is None:
        return None
    mode, content = result
    valid = (
        hashlib.sha256(content).hexdigest() == record.get("sha256")
        and len(content) == record.get("bytes")
        and mode == record.get("mode")
    )
    return (relative, mode, content) if valid else None


def manifest_files(root: Path) -> list[TreeFile] | None:
    try:
        payload = json.loads((root / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        records = payload.get("files")
        if not isinstance(records, list) or not records:
            return None
        expected = {
            "schema": "korpus.source-manifest.v2",
            "kind": "source",
            "manifest_self_excluded": True,
            "file_count": len(records),
            "root_sha256": manifest_root(records),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            return None
        files = [manifest_record((root, record)) for record in records]
        if any(item is None for item in files):
            return None
        exact = [item for item in files if item is not None]
        paths = [path for path, _mode, _content in exact]
        return exact if paths == _working_paths(root) else None
    except (OSError, KeyError, TypeError, ValueError):
        return None
