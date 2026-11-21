"""Freeze verified Git source bytes for source scanners, without generated files."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from korpus.application.release_claim_git_tree import TreeFile, git_files

from scripts.coverage_execution_contract import SOURCE_INPUTS, run_identity, snapshot
from scripts.source_security_contract import require
from scripts.trusted_system_tools import git_environment, git_executable


def checkout_identity(root: Path) -> tuple[str, str]:
    git = git_executable()
    require(git is not None, "trusted Git executable unavailable")
    result = (
        subprocess.run(
            [
                str(git),
                "--no-replace-objects",
                "-C",
                str(root),
                "rev-parse",
                "--show-toplevel",
                "HEAD",
                "HEAD^{tree}",
            ],
            env=git_environment(),
            capture_output=True,
            check=True,
            timeout=30,
        )
        .stdout.decode("utf-8")
        .splitlines()
    )
    require(
        len(result) == 3 and Path(result[0]).resolve() == root.resolve(),
        "checkout root is not the requested Git root",
    )
    return result[1], result[2]


def admit_source(root: Path) -> tuple[dict[str, Any], list[TreeFile]]:
    identity = run_identity()
    require(
        identity["kind"] == "github-actions", "source-security requires a GitHub Actions execution"
    )
    commit, tree = checkout_identity(root)
    require(commit == identity["GITHUB_SHA"], "checkout commit differs from the workflow source")
    files = git_files(root)
    require(bool(files), "working source does not match its exact committed Git inventory")
    assert files is not None
    require(
        all(mode in {"0644", "0755"} for _path, mode, _raw in files),
        "source inventory contains a nonregular member",
    )
    return {
        "run": identity,
        "source_commit_sha": commit,
        "source_tree_oid": tree,
        "source_before": snapshot(root, SOURCE_INPUTS),
    }, files


def freeze_source(destination: Path, files: list[TreeFile]) -> None:
    destination.mkdir(mode=0o700)
    for relative, mode, content in files:
        require(
            not relative.is_absolute() and ".." not in relative.parts and mode in {"0644", "0755"},
            "unsafe source export member",
        )
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
        path.chmod(int(mode, 8))


def verify_frozen_source(destination: Path, files: list[TreeFile]) -> None:
    actual = {
        path.relative_to(destination)
        for path in destination.rglob("*")
        if path.is_symlink() or not path.is_dir()
    }
    require(
        actual == {relative for relative, _mode, _raw in files}, "frozen source inventory changed"
    )
    for relative, mode, content in files:
        path = destination / relative
        require(
            not path.is_symlink() and path.is_file(), "frozen source contains a nonregular file"
        )
        require(
            all(not parent.is_symlink() for parent in path.parents if parent != destination),
            "frozen source contains a symlink parent",
        )
        actual_mode = "0755" if path.stat().st_mode & 0o100 else "0644"
        require(
            actual_mode == mode and path.read_bytes() == content,
            "frozen source bytes or mode changed",
        )


def verify_source_after(root: Path, before: dict[str, Any], files: list[TreeFile]) -> str:
    after, current_files = admit_source(root)
    require(
        after == before and current_files == files,
        "source identity or content changed during scanning",
    )
    return str(after["source_before"]["sha256"])


def runner_temporary(root: Path) -> Path:
    value = os.environ.get("RUNNER_TEMP", "")
    candidate = Path(value)
    require(
        candidate.is_absolute() and candidate.is_dir(),
        "RUNNER_TEMP must be an existing absolute directory",
    )
    require(
        not candidate.resolve().is_relative_to(root.resolve()),
        "scanner temporary files cannot enter the source tree",
    )
    return candidate
