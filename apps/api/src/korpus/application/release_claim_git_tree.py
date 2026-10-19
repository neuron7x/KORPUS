from __future__ import annotations

import io
import subprocess
from pathlib import Path

from scripts.manifest_paths import source_included
from scripts.trusted_system_tools import git_executable

TreeFile = tuple[Path, str, bytes]


def _changed_source(root: Path) -> bool:
    git = git_executable()
    if git is None:
        return True
    try:
        tracked = subprocess.run(
            [git, "-C", str(root), "diff", "--name-only", "-z", "HEAD"],
            capture_output=True,
            check=True,
        ).stdout
        untracked = subprocess.run(
            [git, "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return True
    paths = (Path(raw.decode("utf-8")) for raw in (tracked + untracked).split(b"\0") if raw)
    return any(source_included(path) for path in paths)


def _blob_bytes(root: Path, objects: list[str]) -> list[bytes] | None:
    git = git_executable()
    if git is None:
        return None
    try:
        output = subprocess.run(
            [git, "-C", str(root), "cat-file", "--batch"],
            input="".join(f"{object_id}\n" for object_id in objects).encode("ascii"),
            capture_output=True,
            check=True,
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
    if not separator or len(fields) != 3 or fields[1] != "blob":
        return None
    mode = fields[0][2:] if fields[0] in {"100644", "100755"} else fields[0]
    return relative, mode, fields[2]


def git_files(root: Path) -> list[TreeFile] | None:
    if _changed_source(root):
        return None
    git = git_executable()
    if git is None:
        return None
    try:
        listing = subprocess.run(
            [git, "-C", str(root), "ls-tree", "-r", "-z", "--full-tree", "HEAD"],
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    parsed = [_record(raw) for raw in listing.split(b"\0") if raw]
    if any(record is None for record in parsed):
        return None
    records = [record for record in parsed if record is not None and source_included(record[0])]
    blobs = _blob_bytes(root, [record[2] for record in records])
    if blobs is None:
        return None
    return [
        (relative, mode, content)
        for (relative, mode, _object_id), content in zip(records, blobs, strict=True)
    ] or None
