#!/usr/bin/env python3
"""Bind live assurance provenance to evidence-bearing bytes committed in Git."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SRC = ROOT / "apps/api/src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from korpus.application.evidence_digest import (  # noqa: E402
    EVIDENCE_SOURCE_PATHS,
    digest_source_records,
    evidence_source_path_included,
)


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def committed_evidence_source_digest(ref: str = "HEAD", root: Path = ROOT) -> str:
    """Compute the canonical evidence-source digest from a committed Git ref."""

    try:
        listing = _git(
            root,
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            ref,
            "--",
            *EVIDENCE_SOURCE_PATHS,
        ).split(b"\0")
        names = sorted(
            {
                raw.decode("utf-8")
                for raw in listing
                if raw and evidence_source_path_included(raw.decode("utf-8"))
            }
        )
        return digest_source_records(
            (name, _git(root, "show", f"{ref}:{name}")) for name in names
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f"cannot read evidence-bearing source from Git ref {ref!r}") from error


def evidence_source_binding_failure(
    claimed_digest: object, ref: str = "HEAD", root: Path = ROOT
) -> str | None:
    """Return a fail-closed reason when assurance provenance is not committed source."""

    if not isinstance(claimed_digest, str) or len(claimed_digest) != 64:
        return "assurance evidence source digest is missing or malformed"
    try:
        int(claimed_digest, 16)
    except ValueError:
        return "assurance evidence source digest is missing or malformed"
    actual = committed_evidence_source_digest(ref=ref, root=root)
    if claimed_digest.lower() != actual:
        return "assurance evidence source digest does not match committed HEAD"
    return None
