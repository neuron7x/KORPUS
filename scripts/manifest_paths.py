from __future__ import annotations

import subprocess
from pathlib import Path

EXCLUDED_PARTS = {".git", "dist", "var", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
SOURCE_GENERATED_PREFIXES = {
    ("reports",),
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
        relative.suffix != ".bundle",
        not (relative.parts[:2] == ("infra", "secrets") and relative.suffix == ".txt"),
    )
    return all(checks)


def _git_tracked_paths(root: Path) -> list[Path] | None:
    try:
        probe = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            check=True,
            capture_output=True,
            text=True,
        )
        if probe.stdout.strip() != "true":
            return None
        output = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    paths = [Path(item.decode("utf-8")) for item in output.split(b"\0") if item]
    return sorted((path for path in paths if source_included(path)), key=Path.as_posix)


def _walk_files(root: Path, predicate) -> list[Path]:
    return sorted(
        (
            path.relative_to(root)
            for path in root.rglob("*")
            if path.is_file() and predicate(path.relative_to(root))
        ),
        key=Path.as_posix,
    )


def source_paths(root: Path) -> list[Path]:
    """Committed/staged source paths in a worktree; source paths in a gitless snapshot."""
    return _git_tracked_paths(root) or _walk_files(root, source_included)


def distribution_paths(root: Path) -> list[Path]:
    """Exact deliverable paths, excluding local/runtime debris and the manifest itself."""
    excluded = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
    return _walk_files(
        root,
        lambda relative: (
            not any(part in excluded for part in relative.parts)
            and relative.as_posix() != "DISTRIBUTION_MANIFEST.json"
        ),
    )
