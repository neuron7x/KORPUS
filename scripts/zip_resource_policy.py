"""Finite resource admission for ZIP verification before structural traversal."""

from __future__ import annotations

import zipfile

MAX_ARCHIVE_ENTRIES = 8192
MAX_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_ENTRY_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100.0


def resource_failures(zf: zipfile.ZipFile) -> list[str]:
    infos = zf.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        return [f"archive entry budget exceeded: {len(infos)} > {MAX_ARCHIVE_ENTRIES}"]
    failures: list[str] = []
    total = 0
    for info in infos:
        total += info.file_size
        if info.file_size > MAX_ENTRY_UNCOMPRESSED_BYTES:
            failures.append(
                f"archive entry uncompressed budget exceeded: {info.filename!r} "
                f"{info.file_size} > {MAX_ENTRY_UNCOMPRESSED_BYTES}"
            )
        if info.file_size and info.compress_size == 0:
            failures.append(
                f"archive entry has zero compressed size with non-zero payload: {info.filename!r}"
            )
        elif info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            ratio = info.file_size / info.compress_size
            failures.append(
                f"archive compression ratio exceeded: {info.filename!r} "
                f"{ratio:.2f} > {MAX_COMPRESSION_RATIO:.2f}"
            )
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            failures.append(
                f"archive total uncompressed budget exceeded: {total} > {MAX_TOTAL_UNCOMPRESSED_BYTES}"
            )
            break
    return failures
