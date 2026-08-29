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

from manifest_paths import source_included

ROOT = Path(__file__).resolve().parents[1]
DIGEST_SCOPE = "tracked_tree"


def _included(name: str) -> bool:
    """One definition of what a source is, borrowed rather than copied.

    This module used to carry its own list — four prefixes and three manifest names — while
    manifest_paths.source_included also excluded the release artefacts through
    SOURCE_GENERATED_PREFIXES. They disagreed on six files: CANONICAL_RELEASE_REPORT.json
    and .md, FULL_SSOT_PACKAGE_RECEIPT.json, PACKAGE_BOUNDARY.md, PACKAGE_BUILD.json and a
    LINEAGE manifest.

    The consequence was worse than a mismatch. Those files are written by the release cycle
    itself, so the digest moved every time a report was regenerated, with no change to any
    code — BOUND was unstable by construction and the release unbound itself, reporting it
    as a tree that had changed. And in an archive the digest is computed from the manifest,
    which never listed them: 1354 paths in the repository against 1348 in the package, for
    the same revision.

    Adding six names here would have fixed today's difference. Deleting the second
    definition makes the difference impossible, and the next generated artefact is declared
    in one place.
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
