"""Install the exact official compiler archive before its unchanged full-tree admission."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
import time
import urllib.request
from pathlib import Path, PurePosixPath

from scanner_stdlib_pins import GO_ARCHIVE_SHA256, GO_ARCHIVE_URL

MAX_DOWNLOAD = 128 * 1024 * 1024
MAX_EXPANDED = 300_000_000


def download() -> bytes:
    deadline = time.monotonic() + 120
    chunks, size = [], 0
    with urllib.request.urlopen(GO_ARCHIVE_URL, timeout=30) as response:
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > MAX_DOWNLOAD or time.monotonic() > deadline:
                raise ValueError("official compiler download exceeded its bound")
            chunks.append(block)
    return b"".join(chunks)


def install(raw: bytes, destination: Path) -> Path:
    """Refuse altered bytes before parsing and never merge into an existing toolchain."""
    if len(raw) > MAX_DOWNLOAD or hashlib.sha256(raw).hexdigest() != GO_ARCHIVE_SHA256:
        raise ValueError("official compiler archive digest differs")
    if destination.exists() or destination.is_symlink():
        raise ValueError("compiler destination already exists")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()
        if not members or len(members) > 30_000:
            raise ValueError("compiler archive member budget exceeded")
        names, total = set(), 0
        for member in members:
            name = PurePosixPath(member.name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or not name.parts
                or name.parts[0] != "go"
                or name.as_posix() in names
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("compiler archive member is not a unique regular input")
            names.add(name.as_posix())
            total += member.size
            if member.size < 0 or total > MAX_EXPANDED:
                raise ValueError("compiler archive expanded size exceeded its bound")
        destination.mkdir(mode=0o700)
        archive.extractall(destination, members=members, filter="data")
    return destination / "go"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    root = install(download(), args.destination)
    print(json.dumps({"archive_sha256": GO_ARCHIVE_SHA256, "compiler_root": str(root)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
