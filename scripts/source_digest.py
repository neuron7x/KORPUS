#!/usr/bin/env python3
"""Digest release source trees and evidence-bearing source surfaces."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SRC = ROOT / "apps/api/src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from korpus.application.provenance import (  # noqa: E402
    EVIDENCE_SOURCE_PATHS,
    digest_source_records,
    evidence_source_path_included,
)

EXCLUDED_PREFIXES = ("reports/", "handoff/evidence/", "dist/", "var/")
EXCLUDED_FILES = {"SOURCE_MANIFEST.json", "DISTRIBUTION_MANIFEST.json", "REPOSITORY_MANIFEST.json"}


def _included(name: str) -> bool:
    return name not in EXCLUDED_FILES and not name.startswith(EXCLUDED_PREFIXES)


def _git_at(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def _git(*args: str) -> bytes:
    return _git_at(ROOT, *args)


def _git_paths(ref: str) -> list[Path] | None:
    try:
        listing = _git("ls-tree", "-r", "-z", "--name-only", ref).split(b"\0")
        names = [item.decode() for item in listing if item]
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return sorted(
        (Path(name) for name in names if _included(name)), key=lambda value: value.as_posix()
    )


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


def evidence_source_tree_digest(ref: str = "HEAD", root: Path = ROOT) -> str:
    """Digest evidence-bearing bytes from a committed Git ref.

    Packaging ships ``git archive HEAD``. Release evidence is therefore valid only when
    its live-tree provenance equals this digest of the same evidence-bearing paths from
    the committed ref. The path set and framing are imported from the runtime provenance
    module so the two execution surfaces cannot drift independently.
    """

    try:
        listing = _git_at(
            root,
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            ref,
            "--",
            *EVIDENCE_SOURCE_PATHS,
        ).split(b"\0")
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f"cannot read evidence-bearing source from Git ref {ref!r}") from error

    names = sorted(
        {
            item.decode("utf-8")
            for item in listing
            if item and evidence_source_path_included(item.decode("utf-8"))
        }
    )
    records = ((name, _git_at(root, "show", f"{ref}:{name}")) for name in names)
    return digest_source_records(records)


def validate_evidence_source_binding(
    claimed_digest: object, ref: str = "HEAD", root: Path = ROOT
) -> tuple[bool, str | None, str]:
    """Validate an assurance evidence digest against committed source bytes."""

    actual = evidence_source_tree_digest(ref=ref, root=root)
    if not isinstance(claimed_digest, str) or len(claimed_digest) != 64:
        return False, "assurance evidence source digest is missing or malformed", actual
    try:
        int(claimed_digest, 16)
    except ValueError:
        return False, "assurance evidence source digest is missing or malformed", actual
    if claimed_digest.lower() != actual:
        return False, "assurance evidence source digest does not match committed HEAD", actual
    return True, None, actual


if __name__ == "__main__":
    print(source_tree_digest())
