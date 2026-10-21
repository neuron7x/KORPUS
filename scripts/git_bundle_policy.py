"""Reject Git bundle bytes even when an archive renames the file."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import IO

HEADERS = (b"# v2 git bundle\n", b"# v3 git bundle\n")


def is_bundle_stream(stream: IO[bytes]) -> bool:
    return stream.read(16).startswith(HEADERS)


def is_bundle_path(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name.casefold().rstrip(" .").endswith(".bundle"):
        return True
    with path.open("rb") as stream:
        return is_bundle_stream(stream)


def bundle_zip_failures(zf: zipfile.ZipFile) -> list[str]:
    failures: list[str] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        if info.filename.casefold().rstrip(" .").endswith(".bundle"):
            failures.append(f"git bundle forbidden: {info.filename!r}")
            continue
        with zf.open(info) as stream:
            if is_bundle_stream(stream):
                failures.append(f"git bundle forbidden: {info.filename!r}")
    return failures
