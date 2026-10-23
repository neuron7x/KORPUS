from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from trusted_system_tools import git_environment, git_executable

EXCLUDED_PARTS = {".git", "dist", "var", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
SOURCE_GENERATED_PREFIXES = {
    ("reports",),
    (".verdict-ledger.jsonl",),
    ("handoff", "evidence"),
    ("evidence",),
    ("PACKAGE_BOUNDARY.md",),
    ("PACKAGE_BUILD.json",),
    ("FULL_SSOT_PACKAGE_RECEIPT.json",),
    ("CANONICAL_RELEASE_REPORT.json",),
    ("CANONICAL_RELEASE_REPORT.md",),
}
LOCAL_EXCLUDED_FILES, MANIFEST_NAMES = (
    {".coverage"},
    {"SOURCE_MANIFEST.json", "DISTRIBUTION_MANIFEST.json", "REPOSITORY_MANIFEST.json"},
)


def source_included(relative: Path) -> bool:
    checks = (
        not any(part in EXCLUDED_PARTS for part in relative.parts),
        not any(relative.parts[: len(prefix)] == prefix for prefix in SOURCE_GENERATED_PREFIXES),
        relative.name not in LOCAL_EXCLUDED_FILES,
        not relative.name.startswith(".coverage."),
        relative.name not in MANIFEST_NAMES,
        not (relative.parts[:2] == ("infra", "secrets") and relative.suffix == ".txt"),
    )
    return all(checks)


def _git(root: Path, *args: str) -> bytes:
    executable = git_executable()
    if executable is None:
        raise FileNotFoundError("trusted Git executable unavailable")
    command = [executable, "--no-replace-objects", *args]
    environment = git_environment()
    return subprocess.check_output(command, cwd=root, env=environment, stderr=subprocess.PIPE)


def _git_tracked_paths(root: Path) -> list[Path] | None:
    try:
        if _git(root, "rev-parse", "--show-toplevel").decode().strip() != str(root.resolve()):
            return None
        output = _git(root, "ls-files", "-z")
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    paths = [Path(item.decode("utf-8")) for item in output.split(b"\0") if item]
    return sorted((path for path in paths if source_included(path)), key=Path.as_posix)


def _walk_files(root: Path, predicate: Callable[[Path], bool]) -> list[Path]:
    return sorted(
        (
            path.relative_to(root)
            for path in root.rglob("*")
            if path.is_file() and predicate(path.relative_to(root))
        ),
        key=Path.as_posix,
    )


def source_paths(root: Path) -> list[Path]:
    tracked = _git_tracked_paths(root)
    if tracked is not None:
        return tracked
    marker = root / ".git"
    if marker.exists() or marker.is_symlink():
        raise RuntimeError("git metadata is present but the Git tree cannot be verified")
    return _walk_files(root, source_included)


def distribution_paths(root: Path) -> list[Path]:
    excluded = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
    return _walk_files(
        root,
        lambda relative: (
            not any(part in excluded for part in relative.parts)
            and relative.as_posix() != "DISTRIBUTION_MANIFEST.json"
        ),
    )
