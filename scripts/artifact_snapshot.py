"""Bind ZIP verification and reported SHA-256 to one private byte snapshot."""

from __future__ import annotations

import json
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from snapshot_admission import copy_bounded


def verify_snapshot(
    archive: Path, verifier: Callable[[BinaryIO], tuple[list[str], int]]
) -> tuple[list[str], int, str]:
    """Copy an opened descriptor once; never trust the pathname after admission."""
    with archive.open("rb") as source, tempfile.TemporaryFile(mode="w+b") as snapshot:
        digest = copy_bounded(source, snapshot)
        try:
            failures, files = verifier(snapshot)
        except (RuntimeError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            failures, files = [str(exc)], 0
        return failures, files, digest
