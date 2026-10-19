from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from korpus.application.final_release_provenance import (
    REQUIRED_BUILD_MATERIALS,
    ReleaseBuildContext,
)
from korpus.application.github_release_context import (
    POSITIVE_INTEGER,
    github_release_context_mismatches,
)


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
    except subprocess.CalledProcessError as error:
        raise ValueError(f"git identity check failed: {' '.join(args)}") from error


def local_material_digests(root: Path) -> dict[str, str]:
    return {
        f"file:///{relative}": hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in REQUIRED_BUILD_MATERIALS
    }


def trusted_builder_ids(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    result = {
        str(item)
        for item in payload.get("trusted_builder_ids", ())
        if isinstance(item, str) and item
    }
    if os.getenv("KORPUS_TRUSTED_BUILDER_ID"):
        result.add(os.environ["KORPUS_TRUSTED_BUILDER_ID"])
    return result


def configure_parser(parser: argparse.ArgumentParser, root: Path) -> None:
    for name in (
        "artifact",
        "release-manifest",
        "release-attestation",
        "builder-provenance",
        "builder-attestation",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument(
        "--production-assurance",
        type=Path,
        default=root / "reports/PRODUCTION_ASSURANCE_REPORT.json",
    )
    parser.add_argument("--source-manifest", type=Path, default=root / "SOURCE_MANIFEST.json")
    parser.add_argument("--out", type=Path, default=root / "var/production/final_release-gate.json")


def release_build_context(root: Path, release: str) -> ReleaseBuildContext:
    mismatches = github_release_context_mismatches(os.environ, release)
    if mismatches:
        raise ValueError(f"noncanonical GitHub release context: {mismatches}")
    source_commit = os.getenv("GITHUB_SHA", "")
    run_id, run_attempt = os.getenv("GITHUB_RUN_ID", ""), os.getenv("GITHUB_RUN_ATTEMPT", "")
    if not POSITIVE_INTEGER.fullmatch(run_id) or not POSITIVE_INTEGER.fullmatch(run_attempt):
        raise ValueError("GitHub run id and attempt must be positive integers")
    ref = f"refs/tags/{release}"
    event_commit = _git(root, "rev-parse", "--verify", f"{source_commit}^{{commit}}")
    head_commit = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
    tag_commit = _git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if {event_commit, head_commit, tag_commit} != {source_commit}:
        raise ValueError("GitHub event SHA, release tag, and checked-out HEAD differ")
    return ReleaseBuildContext(
        release=release,
        source_commit_sha=source_commit,
        github_run_id=run_id,
        github_run_attempt=run_attempt,
        expected_materials=local_material_digests(root),
        verification_time=datetime.now(UTC),
    )
