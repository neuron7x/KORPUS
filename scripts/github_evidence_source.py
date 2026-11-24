"""Bind hosted evidence to the actual, clean checkout through the trusted Git boundary."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from coverage_execution_contract import SOURCE_INPUTS, canonical_bytes, snapshot
from github_evidence_transport import GitHubEvidenceError, insist
from github_source_identity import capture_identity_files
from korpus.application.provenance import digest_source_records, evidence_source_path_included
from korpus.application.release_claim_git_tree import TreeFile, _command, git_files
from korpus.application.release_claim_tree import _digest

from scripts.source_security_source import freeze_source, verify_frozen_source


@dataclass(frozen=True)
class Checkout:
    root: Path
    commit: str
    tree: str
    evidence_digest: str
    source_bytes: bytes
    tracked_tree_sha256: str
    tracked_tree_with_mode_sha256: str
    files: tuple[TreeFile, ...]
    identity_files: tuple[TreeFile, ...]

    @property
    def source(self) -> dict[str, Any]:
        return dict(json.loads(self.source_bytes))


def _oid(root: Path, expression: str) -> str:
    invocation = _command(root, "rev-parse", "--verify", expression)
    if invocation is None:
        raise GitHubEvidenceError("trusted Git checkout identity is unavailable")
    command, environment = invocation
    try:
        result = subprocess.run(
            command, env=environment, capture_output=True, check=True, timeout=30
        )
        value = result.stdout.decode("ascii").strip()
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        raise GitHubEvidenceError("cannot establish checkout Git identity") from error
    insist(len(value) == 40 and all(c in "0123456789abcdef" for c in value), "invalid Git OID")
    return value


def capture_checkout(root: Path) -> Checkout:
    root = root.resolve()
    commit = _oid(root, "HEAD^{commit}")
    tree = _oid(root, "HEAD^{tree}")
    files = git_files(root)
    if files is None:
        raise GitHubEvidenceError("checkout differs from its exact committed source tree")
    identity_files = capture_identity_files(root, commit)
    source_members = {path: (mode, content) for path, mode, content in files}
    insist(
        all(
            path not in source_members or source_members[path] == (mode, content)
            for path, mode, content in identity_files
        ),
        "source identity changed during capture",
    )
    records = (
        (path.as_posix(), content)
        for path, _mode, content in files
        if evidence_source_path_included(path.as_posix())
    )
    digest = digest_source_records(records)
    source = snapshot(root, SOURCE_INPUTS)
    insist(_oid(root, "HEAD^{commit}") == commit, "checkout HEAD changed during admission")
    full = digest_source_records((path.as_posix(), content) for path, _mode, content in files)
    return Checkout(
        root,
        commit,
        tree,
        digest,
        canonical_bytes(source),
        full,
        _digest(files),
        tuple(files),
        identity_files,
    )


@contextmanager
def frozen_checkout(checkout: Checkout) -> Iterator[Path]:
    with TemporaryDirectory(prefix="github-source-") as directory:
        root = Path(directory) / "source"
        files = list(checkout.files)
        freeze_source(root, files)
        insist(
            snapshot(root, SOURCE_INPUTS) == checkout.source,
            "captured Git bytes differ from coverage source snapshot",
        )
        yield root
        verify_frozen_source(root, files)
