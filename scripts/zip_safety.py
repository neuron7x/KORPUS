#!/usr/bin/env python3
"""Fail-closed ZIP name/type validation before extraction.
Security property: an archive is extraction-eligible only when every entry has one
canonical relative POSIX name, no aliases/collisions, and is a regular file or directory.
The validator is intentionally independent of ``ZipFile.extractall`` path handling.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

_DRIVE = re.compile(r"^[A-Za-z]:")
from importlib import import_module

resource_failures = import_module(
    f"{__package__ + chr(46) if __package__ else chr(39) * 0}zip_resource_policy"
).resource_failures


def _basic_name_failure(name: str) -> str | None:
    checks = (
        (not name, "empty archive entry name"),
        ("\x00" in name, f"NUL byte in archive entry: {name!r}"),
        ("\\" in name, f"backslash path separator rejected: {name!r}"),
        (unicodedata.normalize("NFC", name) != name, f"non-NFC archive entry rejected: {name!r}"),
        (
            name.startswith("/") or bool(_DRIVE.match(name)),
            f"absolute archive path rejected: {name!r}",
        ),
    )
    return next((message for failed, message in checks if failed), None)


def _canonical_name(name: str) -> tuple[str | None, str | None]:
    basic_failure = _basic_name_failure(name)
    if basic_failure:
        return None, basic_failure
    is_dir = name.endswith("/")
    body = name[:-1] if is_dir else name
    if not body:
        return None, f"archive root entry rejected: {name!r}"
    parts = body.split("/")
    if set(parts) & {"", ".", ".."}:
        return None, f"non-canonical archive path rejected: {name!r}"
    canonical = PurePosixPath(*parts).as_posix() + ("/" if is_dir else "")
    if canonical != name:
        return None, f"archive path normalization mismatch: {name!r}"
    return canonical, None


def _type_failure(info: zipfile.ZipInfo) -> str | None:
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if info.is_dir():
        if file_type not in {0, stat.S_IFDIR}:
            return f"directory entry carries non-directory mode: {info.filename!r}"
        return None
    if file_type not in {0, stat.S_IFREG}:
        return f"non-regular archive entry rejected: {info.filename!r} mode={mode:o}"
    return None


def _record_entry(
    info: zipfile.ZipInfo,
    exact: set[str],
    folded: dict[str, str],
    file_paths: set[str],
    dir_paths: set[str],
) -> list[str]:
    canonical, path_failure = _canonical_name(info.filename)
    if path_failure:
        return [path_failure]
    assert canonical is not None
    failures: list[str] = []
    if canonical in exact:
        failures.append(f"duplicate archive entry rejected: {canonical!r}")
    exact.add(canonical)

    normalized_path = canonical.rstrip("/")
    alias_key = normalized_path.casefold()
    prior = folded.get(alias_key)
    if prior is not None and prior != normalized_path:
        failures.append(f"casefold/alias collision rejected: {prior!r} vs {canonical!r}")
    else:
        folded[alias_key] = normalized_path

    type_failure = _type_failure(info)
    if type_failure:
        failures.append(type_failure)
    (dir_paths if info.is_dir() else file_paths).add(normalized_path)
    return failures


def _structural_collision_failures(file_paths: set[str], dir_paths: set[str]) -> list[str]:
    failures = [
        f"file/directory alias collision rejected: {path!r}"
        for path in sorted(file_paths & dir_paths)
    ]
    for path in sorted(file_paths):
        parts = path.split("/")
        parents = ("/".join(parts[:index]) for index in range(1, len(parts)))
        failures.extend(
            f"file/directory prefix collision rejected: {parent!r} prefixes {path!r}"
            for parent in parents
            if parent in file_paths
        )
    return failures


def safety_failures(zf: zipfile.ZipFile) -> list[str]:
    resource_violations = resource_failures(zf)
    if resource_violations:
        return sorted(set(resource_violations))
    exact: set[str] = set()
    folded: dict[str, str] = {}
    file_paths: set[str] = set()
    dir_paths: set[str] = set()
    failures = [
        failure
        for info in zf.infolist()
        for failure in _record_entry(info, exact, folded, file_paths, dir_paths)
    ]
    failures.extend(_structural_collision_failures(file_paths, dir_paths))
    return sorted(set(failures))


def verify_zip_safety(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as zf:
            return safety_failures(zf)
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"invalid ZIP: {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    archive = parser.parse_args().archive.resolve()
    failures = verify_zip_safety(archive)
    print(
        json.dumps({"safe": not failures, "archive": str(archive), "failures": failures}, indent=2)
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
