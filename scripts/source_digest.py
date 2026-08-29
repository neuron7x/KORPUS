#!/usr/bin/env python3
"""Digest the complete release source tree, excluding generated evidence.

Scope is DIGEST_SCOPE below. This is NOT the same measurement as
korpus.application.provenance.compute_source_digest, which covers twenty declared
evidence-bearing paths. Both were written into a field named `source_tree_sha256`, so a
report signed by one and verified against the other fails as "unbound" — a message about
the tree changing, when the tree did not change and two different scopes were compared.
Carry `digest_scope` beside the value and compare scopes before hashes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIGEST_SCOPE = "tracked_tree"
EXCLUDED_PREFIXES = ("reports/", "handoff/evidence/", "dist/", "var/")
EXCLUDED_FILES = {"SOURCE_MANIFEST.json", "DISTRIBUTION_MANIFEST.json", "REPOSITORY_MANIFEST.json"}


def _included(name: str) -> bool:
    return name not in EXCLUDED_FILES and not name.startswith(EXCLUDED_PREFIXES)


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def _git_paths(ref: str) -> list[Path] | None:
    try:
        listing = _git("ls-tree", "-r", "-z", "--name-only", ref).split(b"\0")
        names = [item.decode() for item in listing if item]
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    included = sorted(
        (Path(name) for name in names if _included(name)), key=lambda value: value.as_posix()
    )
    return included or None


def _archive_paths() -> list[Path]:
    manifest_path = ROOT / "SOURCE_MANIFEST.json"
    if not manifest_path.is_file():
        raise RuntimeError("neither Git metadata nor SOURCE_MANIFEST.json is available")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.get("files")
    if not isinstance(records, list):
        raise RuntimeError("invalid source manifest")
    paths: list[Path] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise RuntimeError("invalid source manifest record")
        relative = record["path"]
        if not _included(relative):
            continue
        path = (ROOT / relative).resolve()
        if ROOT not in path.parents or not path.is_file():
            raise RuntimeError(f"source-manifest file is missing or unsafe: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256"):
            raise RuntimeError(f"source-manifest hash mismatch: {relative}")
        paths.append(Path(relative))
    return sorted(paths, key=lambda value: value.as_posix())


def included_paths(ref: str = "HEAD") -> list[Path]:
    return _git_paths(ref) or _archive_paths()


def source_tree_digest(ref: str = "HEAD") -> str:
    git_paths = _git_paths(ref)
    paths = git_paths if git_paths is not None else _archive_paths()
    hasher = hashlib.sha256()
    for relative_path in paths:
        relative = relative_path.as_posix().encode("utf-8")
        content = (
            _git("show", f"{ref}:{relative_path.as_posix()}")
            if git_paths is not None
            else (ROOT / relative_path).read_bytes()
        )
        hasher.update(len(relative).to_bytes(4, "big"))
        hasher.update(relative)
        hasher.update(len(content).to_bytes(8, "big"))
        hasher.update(content)
    return hasher.hexdigest()


if __name__ == "__main__":
    print(source_tree_digest())
