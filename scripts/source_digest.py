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
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api/src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from korpus.application.provenance_surface import EVIDENCE_SOURCE_PATHS
from korpus.application.release_claim_manifest_tree import manifest_files
from manifest_paths import source_included
from trusted_system_tools import git_environment, git_executable

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
    executable = git_executable()
    if executable is None:
        raise FileNotFoundError("trusted Git executable unavailable")
    return subprocess.run(
        [executable, "--no-replace-objects", "-C", str(ROOT), *args],
        cwd=ROOT,
        env=git_environment(),
        check=True,
        capture_output=True,
    ).stdout


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


def _archive_files() -> list[tuple[Path, bytes]]:
    """Use exact verified gitless snapshot bytes, not a self-declared file subset."""
    marker = ROOT / ".git"
    if marker.exists() or marker.is_symlink():
        raise RuntimeError("git metadata is present but the Git tree cannot be verified")
    files = manifest_files(ROOT)
    if files is None:
        raise RuntimeError("restored source manifest is incomplete or ambiguous")
    return [(path, content) for path, _mode, content in files]


def _archive_paths() -> list[Path]:
    return [path for path, _content in _archive_files()]


def _same_evidence_source(commit: str, head: str) -> bool:
    try:
        _git("diff", "--quiet", commit, head, "--", *EVIDENCE_SOURCE_PATHS)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


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
    files = (
        ((path, _git("show", f"{ref}:{path.as_posix()}")) for path in git_paths)
        if git_paths is not None
        else _archive_files()
    )
    hasher = hashlib.sha256()
    for relative_path, content in files:
        relative = relative_path.as_posix().encode("utf-8")
        hasher.update(len(relative).to_bytes(4, "big"))
        hasher.update(relative)
        hasher.update(len(content).to_bytes(8, "big"))
        hasher.update(content)
    return hasher.hexdigest()


if __name__ == "__main__":
    print(source_tree_digest())
