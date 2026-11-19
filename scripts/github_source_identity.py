"""Capture fixed generated identity blobs without changing existing source digest scopes."""

from __future__ import annotations

import subprocess
from pathlib import Path

from github_evidence_transport import MAX_JSON_BYTES, GitHubEvidenceError, insist
from korpus.application.release_claim_git_tree import TreeFile, _command, _record, _working_file

IDENTITY_PATHS = (
    "PACKAGE_BUILD.json",
    "SOURCE_MANIFEST.json",
    "apps/api/src/korpus/release.json",
)


def _git_bytes(root: Path, *arguments: str) -> bytes:
    invocation = _command(root, *arguments)
    if invocation is None:
        raise GitHubEvidenceError("trusted Git source identity is unavailable")
    command, environment = invocation
    try:
        return subprocess.run(
            command, env=environment, capture_output=True, check=True, timeout=30
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise GitHubEvidenceError("cannot capture committed source identity") from error


def _identity_file(root: Path, record: tuple[Path, str, str]) -> TreeFile:
    path, mode, object_id = record
    insist(mode in {"0644", "0755"}, "source identity must be a regular committed file")
    size = int(_git_bytes(root, "cat-file", "-s", object_id))
    insist(0 < size <= MAX_JSON_BYTES, "source identity blob exceeds its byte budget")
    payload = _git_bytes(root, "cat-file", "blob", object_id)
    insist(len(payload) == size, "source identity blob changed its declared size")
    insist(
        _working_file(root / path) == (mode, payload),
        "source identity differs from committed bytes or mode",
    )
    return path, mode, payload


def capture_identity_files(root: Path, commit: str) -> tuple[TreeFile, ...]:
    listing = _git_bytes(root, "ls-tree", "-r", "-z", "--full-tree", commit, "--", *IDENTITY_PATHS)
    parsed = [_record(raw) for raw in listing.split(b"\0") if raw]
    insist(all(record is not None for record in parsed), "invalid committed source identity record")
    records = [record for record in parsed if record is not None]
    insist(
        tuple(record[0].as_posix() for record in records) == IDENTITY_PATHS,
        "committed source identity census is incomplete or ambiguous",
    )
    return tuple(_identity_file(root, record) for record in records)
