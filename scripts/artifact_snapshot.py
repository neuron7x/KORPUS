"""Bind ZIP verification and reported SHA-256 to one private byte snapshot."""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO


def verify_snapshot(
    archive: Path, verifier: Callable[[BinaryIO], tuple[list[str], int]]
) -> tuple[list[str], int, str]:
    """Copy an opened descriptor once; never trust the pathname after admission."""
    with archive.open("rb") as source, tempfile.TemporaryFile(mode="w+b") as snapshot:
        digest = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b""):
            snapshot.write(block)
            digest.update(block)
        snapshot.seek(0)
        try:
            failures, files = verifier(snapshot)
        except (RuntimeError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            failures, files = [str(exc)], 0
        return failures, files, digest.hexdigest()
