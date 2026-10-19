from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

from korpus.application.release_claim_git_tree import TreeFile, git_files
from scripts.manifest_paths import source_included


def _digest(files: list[TreeFile]) -> str:
    hasher = hashlib.sha256()
    for relative, mode, content in sorted(files, key=lambda item: item[0].as_posix()):
        name = relative.as_posix().encode("utf-8")
        hasher.update(len(name).to_bytes(4, "big"))
        hasher.update(name)
        hasher.update(mode.encode("ascii"))
        hasher.update(len(content).to_bytes(8, "big"))
        hasher.update(content)
    return hasher.hexdigest()


def _manifest_record(candidate: tuple[Path, object]) -> TreeFile | None:
    root, record = candidate
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        return None
    relative = Path(record["path"])
    if relative.is_absolute() or ".." in relative.parts or not source_included(relative):
        return None
    try:
        target = root / relative
        content = target.read_bytes()
        mode = f"0{stat.S_IMODE(target.stat().st_mode):o}"
    except OSError:
        return None
    valid = (
        hashlib.sha256(content).hexdigest() == record.get("sha256")
        and len(content) == record.get("bytes")
        and mode == record.get("mode")
    )
    return (relative, mode, content) if valid else None


def _manifest_files(root: Path) -> list[TreeFile] | None:
    try:
        payload = json.loads((root / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    records = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return None
    included = [
        record
        for record in records
        if isinstance(record, dict)
        and isinstance(record.get("path"), str)
        and source_included(Path(record["path"]))
    ]
    files = [_manifest_record((root, record)) for record in included]
    if any(record is None for record in files):
        return None
    exact = [record for record in files if record is not None]
    paths = [path for path, _mode, _content in exact]
    return exact if exact and len(paths) == len(set(paths)) else None


def tracked_tree_digest(root: Path) -> str | None:
    """Digest exact committed source bytes, or an exact source-manifest restoration."""
    files = git_files(root) if (root / ".git").exists() else _manifest_files(root)
    return _digest(files) if files else None
