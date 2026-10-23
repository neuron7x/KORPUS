from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable, Iterable
from pathlib import Path


def regular_paths(root: Path, candidates: Iterable[Path], subject: str) -> list[Path]:
    files: list[Path] = []
    for relative in candidates:
        try:
            mode = (root / relative).lstat().st_mode
        except OSError as error:
            raise RuntimeError(f"{subject} is unreadable: {relative}") from error
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise RuntimeError(f"{subject} is not a regular file: {relative}")
        files.append(relative)
    return sorted(files, key=Path.as_posix)


def walk_regular_paths(root: Path, predicate: Callable[[Path], bool], subject: str) -> list[Path]:
    return regular_paths(
        root,
        (path.relative_to(root) for path in root.rglob("*") if predicate(path.relative_to(root))),
        subject,
    )


def copy_regular_files(root: Path, stage: Path, paths: Iterable[Path]) -> None:
    for relative in paths:
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(root / relative, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as error:
            raise RuntimeError(f"package source cannot be opened safely: {relative}") from error
        with os.fdopen(descriptor, "rb") as source, target.open("wb") as destination:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(f"package source is not a regular file: {relative}")
            shutil.copyfileobj(source, destination)
        target.chmod(stat.S_IMODE(metadata.st_mode))
