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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api/src"))

from korpus.application.provenance_surface import EVIDENCE_SOURCE_PATHS
from manifest_paths import source_included

ROOT = Path(__file__).resolve().parents[1]
DIGEST_SCOPE = "tracked_tree"


def _included(name: str) -> bool:
    """One definition of what a source is, borrowed rather than copied.

    The former second exclusion list disagreed with `manifest_paths` on six generated
    release files. Their regeneration moved this digest without changing source, while an
    archive omitted them. Borrowing the predicate makes repository and archive scopes one.
    """
    return bool(source_included(Path(name)))


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


def _same_evidence_source(commit: str, head: str) -> bool:
    return (
        subprocess.run(
            ["git", "diff", "--quiet", commit, head, "--", *EVIDENCE_SOURCE_PATHS],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def commits_with_identical_source(ref: str = "HEAD", depth: int = 64) -> tuple[str, ...]:
    """Walk every still-identical parent path; prune each path at its first source change.

    A merge may have a stale first parent and a verified, source-identical second parent.
    Linear history traversal lost the latter and invalidated evidence after a normal merge.
    """
    try:
        head = _git("rev-parse", ref).decode().strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ()

    accepted: list[str] = []
    frontier = [head]
    seen: set[str] = set()
    while frontier and len(accepted) < depth:
        commit = frontier.pop(0)
        if commit in seen:
            continue
        seen.add(commit)
        accepted.append(commit)
        try:
            parents = _git("show", "-s", "--format=%P", commit).decode().split()
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ()
        frontier.extend(
            parent
            for parent in parents
            if parent not in seen and _same_evidence_source(parent, head)
        )
    return tuple(accepted)

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
