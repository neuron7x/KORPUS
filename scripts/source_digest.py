#!/usr/bin/env python3
"""Digest the complete committed release tree, excluding generated evidence."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PREFIXES = ("reports/", "dist/", "var/")
EXCLUDED_FILES = {"REPOSITORY_MANIFEST.json"}


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def included_paths(ref: str = "HEAD") -> list[Path]:
    names = [item.decode() for item in _git("ls-tree", "-r", "-z", "--name-only", ref).split(b"\0") if item]
    return sorted(
        (
            Path(name)
            for name in names
            if name not in EXCLUDED_FILES and not name.startswith(EXCLUDED_PREFIXES)
        ),
        key=lambda value: value.as_posix(),
    )


def source_tree_digest(ref: str = "HEAD") -> str:
    hasher = hashlib.sha256()
    for relative_path in included_paths(ref):
        relative = relative_path.as_posix().encode("utf-8")
        content = _git("show", f"{ref}:{relative_path.as_posix()}")
        hasher.update(len(relative).to_bytes(4, "big"))
        hasher.update(relative)
        hasher.update(len(content).to_bytes(8, "big"))
        hasher.update(content)
    return hasher.hexdigest()


if __name__ == "__main__":
    print(source_tree_digest())
