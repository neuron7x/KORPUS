from __future__ import annotations

import hashlib
from pathlib import Path

from korpus.application.release_claim_git_tree import TreeFile, git_files
from korpus.application.release_claim_manifest_tree import manifest_files as _manifest_files


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


def tracked_tree_digest(root: Path) -> str | None:
    """Digest an exact committed source tree or a verified gitless manifest snapshot."""
    marker = root / ".git"
    files = git_files(root) if marker.exists() or marker.is_symlink() else _manifest_files(root)
    return _digest(files) if files else None
