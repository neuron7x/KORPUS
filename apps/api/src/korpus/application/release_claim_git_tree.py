from __future__ import annotations

import io
import os
import stat
import subprocess
from pathlib import Path

from scripts.manifest_paths import source_included
from scripts.trusted_system_tools import git_environment, git_executable

TreeFile = tuple[Path, str, bytes]


def _git_directory(root: Path) -> Path | None:
    marker = root.resolve() / ".git"
    if marker.is_symlink():
        return None
    if marker.is_dir():
        return marker.resolve()
    if not marker.is_file():
        return None
    try:
        lines = marker.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    if len(lines) != 1 or not lines[0].startswith("gitdir: "):
        return None
    declared = Path(lines[0].removeprefix("gitdir: "))
    candidate = declared if declared.is_absolute() else marker.parent / declared
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.is_dir() else None


def _command(root: Path, *arguments: str) -> tuple[list[str], dict[str, str]] | None:
    git = git_executable()
    directory = _git_directory(root)
    if git is None or directory is None:
        return None
    worktree = root.resolve()
    command = [
        git,
        "--no-replace-objects",
        f"--git-dir={directory}",
        f"--work-tree={worktree}",
        "-c",
        f"core.worktree={worktree}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        *arguments,
    ]
    return command, git_environment()


def _blob_bytes(root: Path, objects: list[str]) -> list[bytes] | None:
    invocation = _command(root, "cat-file", "--batch")
    if invocation is None:
        return None
    command, environment = invocation
    try:
        output = subprocess.run(
            command,
            input="".join(f"{object_id}\n" for object_id in objects).encode("ascii"),
            capture_output=True,
            check=True,
            env=environment,
        ).stdout
        stream = io.BytesIO(output)
        blobs: list[bytes] = []
        for object_id in objects:
            fields = stream.readline().decode("ascii").rstrip("\n").split()
            if len(fields) != 3 or fields[:2] != [object_id, "blob"]:
                return None
            content = stream.read(int(fields[2]))
            if len(content) != int(fields[2]) or stream.read(1) != b"\n":
                return None
            blobs.append(content)
        return blobs if stream.read() == b"" else None
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError):
        return None


def _record(raw: bytes) -> tuple[Path, str, str] | None:
    metadata, separator, name = raw.partition(b"\t")
    try:
        fields = metadata.decode("ascii").split()
        relative = Path(name.decode("utf-8"))
    except UnicodeError:
        return None
    if (
        not separator
        or len(fields) != 3
        or fields[1] != "blob"
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        return None
    mode = fields[0][2:] if fields[0] in {"100644", "100755"} else fields[0]
    return relative, mode, fields[2]


def _working_file(path: Path) -> tuple[str, bytes] | None:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            return "120000", os.readlink(path).encode("utf-8")
        if not stat.S_ISREG(metadata.st_mode):
            return None
        mode = "0755" if metadata.st_mode & stat.S_IXUSR else "0644"
        return mode, path.read_bytes()
    except (OSError, UnicodeError):
        return None


def _working_paths(root: Path) -> list[Path] | None:
    try:
        return sorted(
            (
                path.relative_to(root)
                for path in root.rglob("*")
                if (path.is_file() or path.is_symlink()) and source_included(path.relative_to(root))
            ),
            key=Path.as_posix,
        )
    except OSError:
        return None


def _tree_records(listing: bytes) -> list[tuple[Path, str, str]] | None:
    parsed = [_record(raw) for raw in listing.split(b"\0") if raw]
    if any(record is None for record in parsed):
        return None
    records = [record for record in parsed if record is not None and source_included(record[0])]
    paths = [record[0] for record in records]
    return records if records and len(paths) == len(set(paths)) else None


def _worktree_matches(root: Path, files: list[TreeFile]) -> bool:
    expected_paths = [relative for relative, _mode, _content in files]
    actual_paths = _working_paths(root)
    return actual_paths == expected_paths and all(
        _working_file(root / relative) == (mode, content) for relative, mode, content in files
    )


def git_files(root: Path) -> list[TreeFile] | None:
    invocation = _command(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
    if invocation is None:
        return None
    command, environment = invocation
    try:
        listing = subprocess.run(
            command,
            capture_output=True,
            check=True,
            env=environment,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    records = _tree_records(listing)
    if records is None:
        return None
    blobs = _blob_bytes(root, [record[2] for record in records])
    if blobs is None:
        return None
    files = [
        (relative, mode, content)
        for (relative, mode, _object_id), content in zip(records, blobs, strict=True)
    ]
    return files if _worktree_matches(root, files) else None
