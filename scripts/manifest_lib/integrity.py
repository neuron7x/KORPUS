from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_root(tmp: Path) -> Path:
    """Descend only when the archive has exactly one top-level directory and nothing else."""
    entries = list(tmp.iterdir())
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp


def mode_string(path: Path, *, source: bool = False) -> str:
    mode = path.stat().st_mode & 0o777
    mode = (0o755 if mode & 0o111 else 0o644) if source else mode
    return f"{mode:04o}"


def canonical_source_mode(mode: str) -> str:
    """Source identity commits executable intent, not the builder's ambient umask."""
    numeric = int(mode, 8)
    return f"{(0o755 if numeric & 0o111 else 0o644):04o}"


def file_record(path: Path, relative: Path, *, source: bool = False) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": relative.as_posix(),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "mode": mode_string(path, source=source),
    }


def manifest_root(records: list[dict[str, object]]) -> str:
    canonical = "".join(
        f'{item["path"]}\0{item["mode"]}\0{item["sha256"]}\n' for item in records
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def manifest_failures(manifest: dict[str, object], records: list[dict[str, object]]) -> list[str]:
    return [] if manifest.get("file_count") == len(records) and manifest.get("root_sha256") == manifest_root(records) else ["manifest aggregate integrity mismatch"]


def archive_modes(zf: zipfile.ZipFile, root_name: str) -> dict[str, str]:
    prefix = f"{root_name}/" if root_name else ""
    result: dict[str, str] = {}
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename[len(prefix):] if prefix and info.filename.startswith(prefix) else info.filename
        if name != "DISTRIBUTION_MANIFEST.json":
            result[name] = f"{(info.external_attr >> 16) & 0o777:04o}"
    return result


def record_failures(path: Path, record: dict[str, object], archive_mode: str | None = None) -> list[str]:
    content = path.read_bytes()
    relative = str(record.get("path"))
    failures: list[str] = []
    if record.get("bytes") != len(content) or record.get("sha256") != hashlib.sha256(content).hexdigest():
        failures.append(f"digest mismatch: {relative}")
    actual_mode = archive_mode if archive_mode is not None else mode_string(path)
    if record.get("mode") != actual_mode:
        failures.append(f"mode mismatch: {relative} expected={record.get('mode')} actual={actual_mode}")
    return failures
