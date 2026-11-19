"""Inspect the pinned archive in memory and extract only its regular x86-64 ELF."""

from __future__ import annotations

import gzip
import hashlib
import io
import re
import tarfile
from pathlib import Path
from typing import Any

from scripts.scanner_engine_download import (
    ARCHIVE_SHA256,
    ARCHIVE_SIZE,
    RELEASE_URL,
    download_archive,
    verify_archive,
)
from scripts.source_security_contract import require

MAX_EXPANDED = 96 * 1024 * 1024
MAX_BINARY = 64 * 1024 * 1024
MAX_MEMBERS = 16


def _elf(raw: bytes) -> None:
    require(
        len(raw) >= 64
        and raw[:7] == b"\x7fELF\x02\x01\x01"
        and int.from_bytes(raw[16:18], "little") in {2, 3}
        and int.from_bytes(raw[18:20], "little") == 62,
        "release member is not an ELF64 little-endian x86-64 executable",
    )


def extract_binary(raw: bytes, destination: Path) -> tuple[Path, list[dict[str, Any]]]:
    """Authenticate before decompression; never use tar extraction or archive modes."""
    verify_archive(raw)
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        expanded = compressed.read(MAX_EXPANDED + 1)
    require(len(expanded) <= MAX_EXPANDED, "release expands beyond its byte budget")
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    binary: bytes | None = None
    with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as archive:
        for member in archive:
            require(len(members) < MAX_MEMBERS, "release has too many members")
            require(
                member.isreg()
                and not member.pax_headers
                and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", member.name) is not None
                and member.name not in {".", ".."}
                and member.name not in seen
                and 0 <= member.size <= MAX_BINARY,
                "unsafe, duplicate or oversized release member",
            )
            seen.add(member.name)
            members.append({"name": member.name, "size": member.size})
            if member.name == "gitleaks":
                stream = archive.extractfile(member)
                require(stream is not None, "release binary is unreadable")
                assert stream is not None
                binary = stream.read(MAX_BINARY + 1)
                require(len(binary) == member.size, "release binary is truncated")
    require(binary is not None, "release contains no unique gitleaks executable")
    assert binary is not None
    _elf(binary)
    destination.mkdir(mode=0o700)
    path = destination / "gitleaks"
    with path.open("xb") as output:
        output.write(binary)
    path.chmod(0o500)
    return path, members


def acquire_binary(destination: Path) -> tuple[Path, dict[str, Any]]:
    raw, redirect_hosts = download_archive()
    binary, members = extract_binary(raw, destination)
    return binary, {
        "release_id": 299662760,
        "asset_id": 378332058,
        "url": RELEASE_URL,
        "archive_size": ARCHIVE_SIZE,
        "archive_sha256": ARCHIVE_SHA256,
        "archive_members": members,
        "redirect_hosts": redirect_hosts,
        "binary_size": binary.stat().st_size,
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "intended_source_commit": "83d9cd684c87d95d656c1458ef04895a7f1cbd8e",
        "source_build_attested": False,
        "identity_basis": "fixed release bytes; runtime version and engine checked separately",
    }
