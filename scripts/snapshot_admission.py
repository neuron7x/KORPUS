"""Bound ZIP input and reject concurrent mutation before semantic verification."""

from __future__ import annotations

import hashlib
import os
import stat
from typing import BinaryIO

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


def copy_bounded(source: BinaryIO, snapshot: BinaryIO) -> str:
    """Copy exactly the descriptor's admitted bytes into a private snapshot."""
    before = os.fstat(source.fileno())
    if not stat.S_ISREG(before.st_mode):
        raise RuntimeError("archive descriptor must be a regular file")
    if before.st_size > MAX_ARCHIVE_BYTES:
        raise RuntimeError("compressed archive input budget exceeded")
    digest = hashlib.sha256()
    remaining = before.st_size
    while remaining:
        block = source.read(min(1024 * 1024, remaining))
        if not block:
            raise RuntimeError("archive changed during snapshot: premature EOF")
        if snapshot.write(block) != len(block):
            raise RuntimeError("archive snapshot write incomplete")
        digest.update(block)
        remaining -= len(block)
    after = os.fstat(source.fileno())
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
        or source.read(1)
    ):
        raise RuntimeError("archive changed during snapshot")
    snapshot.seek(0)
    return digest.hexdigest()
