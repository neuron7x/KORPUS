"""Small neutral Git fixtures, including an isolated deleted historical blob."""

from __future__ import annotations

import hashlib
import re
import stat
import subprocess
import zlib
from pathlib import Path
from typing import Any

from scripts.source_security_contract import require
from scripts.trusted_system_tools import git_environment, git_executable

VALID_TEXT = b"NEUTRAL_ENGINE_BEGIN text NEUTRAL_ENGINE_END\n"
INVALID_TEXT = b"NEUTRAL_ENGINE_BEGIN \xff NEUTRAL_ENGINE_END\n"
CANARY_CONFIG = b"""title = "Neutral engine boundary diagnostic"
[[rules]]
id = "neutral-engine-boundary"
description = "Neutral anchored match spanning a controlled byte"
regex = '''(?m)^NEUTRAL_ENGINE_BEGIN .* NEUTRAL_ENGINE_END$'''
"""


def fixture_git(root: Path, arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    git = git_executable()
    require(git is not None, "trusted Git executable unavailable for neutral fixture")
    environment = git_environment()
    environment.update(
        GIT_AUTHOR_NAME="Neutral Diagnostic",
        GIT_AUTHOR_EMAIL="neutral@example.invalid",
        GIT_COMMITTER_NAME="Neutral Diagnostic",
        GIT_COMMITTER_EMAIL="neutral@example.invalid",
        GIT_AUTHOR_DATE="2000-01-01T00:00:00+00:00",
        GIT_COMMITTER_DATE="2000-01-01T00:00:00+00:00",
    )
    return subprocess.run(
        [
            str(git),
            "--no-replace-objects",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "-C",
            str(root),
            *arguments,
        ],
        env=environment,
        capture_output=True,
        check=False,
        timeout=30,
    )


def checked_git(root: Path, arguments: list[str]) -> bytes:
    result = fixture_git(root, arguments)
    require(result.returncode == 0, "neutral fixture Git construction failed")
    return result.stdout


def _initialize(root: Path) -> None:
    root.mkdir(mode=0o700)
    checked_git(root, ["init", "--quiet", "--initial-branch=diagnostic", "--object-format=sha1"])
    (root / "canary.toml").write_bytes(CANARY_CONFIG)


def utf8_fixture(root: Path) -> str:
    _initialize(root)
    (root / "valid.txt").write_bytes(VALID_TEXT)
    (root / "invalid.txt").write_bytes(INVALID_TEXT)
    checked_git(root, ["add", "--", "valid.txt", "invalid.txt"])
    checked_git(root, ["commit", "--quiet", "-m", "neutral UTF-8 boundary"])
    return checked_git(root, ["rev-parse", "HEAD"]).decode().strip()


def history_fixture(root: Path) -> dict[str, str]:
    _initialize(root)
    (root / "deleted.txt").write_bytes(VALID_TEXT)
    checked_git(root, ["add", "--", "deleted.txt"])
    checked_git(root, ["commit", "--quiet", "-m", "neutral historical marker"])
    blob = checked_git(root, ["rev-parse", "HEAD:deleted.txt"]).decode().strip()
    checked_git(root, ["rm", "--quiet", "--", "deleted.txt"])
    (root / "current.txt").write_text("neutral current content\n")
    checked_git(root, ["add", "--", "current.txt"])
    checked_git(root, ["commit", "--quiet", "-m", "remove neutral marker"])
    return {
        "head": checked_git(root, ["rev-parse", "HEAD"]).decode().strip(),
        "tree": checked_git(root, ["rev-parse", "HEAD^{tree}"]).decode().strip(),
        "deleted_blob": blob,
    }


def damage_history(root: Path, identity: dict[str, str]) -> None:
    """Only remove the known fixture's loose blob after verifying its Git identity."""
    blob = identity["deleted_blob"]
    require(re.fullmatch(r"[a-f0-9]{40}", blob) is not None, "invalid fixture blob ID")
    path = root / ".git" / "objects" / blob[:2] / blob[2:]
    require(
        stat.S_ISREG(path.lstat().st_mode)
        and path.stat().st_size < 1024
        and all(not parent.is_symlink() for parent in path.parents),
        "historical fixture blob is not an owned small loose object",
    )
    decoder = zlib.decompressobj()
    object_bytes = decoder.decompress(path.read_bytes(), 128)
    require(
        decoder.eof
        and not decoder.unused_data
        and object_bytes == b"blob " + str(len(VALID_TEXT)).encode() + b"\0" + VALID_TEXT
        and hashlib.sha1(object_bytes, usedforsecurity=False).hexdigest() == blob,
        "historical fixture blob content or identity differs",
    )
    path.unlink()
    require(
        checked_git(root, ["rev-parse", "HEAD"]).decode().strip() == identity["head"]
        and checked_git(root, ["rev-parse", "HEAD^{tree}"]).decode().strip() == identity["tree"]
        and checked_git(root, ["show", "HEAD:current.txt"]) == b"neutral current content\n",
        "fixture current source changed while removing the historical blob",
    )


def history_control(root: Path, head: str) -> dict[str, Any]:
    results = {}
    commands = {
        "git_log": ["log", "-p", "-U0", head, "--full-history", "--diff-merges=first-parent"],
        "git_fsck": ["fsck", "--full", "--strict", "--no-reflogs"],
    }
    for name, command in commands.items():
        result = fixture_git(root, command)
        results[name] = {
            "arguments": command,
            "exit_code": result.returncode,
            "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            "stdout_bytes": len(result.stdout),
            "stderr_bytes": len(result.stderr),
        }
    return results
