"""Authenticate the complete compiler and upstream input trees before execution."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path
from typing import Any

from scripts.scanner_stdlib_pins import (
    GO_EXECUTABLE_SHA256,
    GO_TOOLCHAIN_BYTES,
    GO_TOOLCHAIN_FILES,
    GO_TOOLCHAIN_SHA256,
    SOURCE_INVENTORIES,
    UNCHANGED_FILES,
)
from scripts.source_security_contract import require


def digest(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), "expected a regular pinned input")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_inventory(root: Path, *, compiler: bool = False) -> dict[str, Any]:
    """Hash relative path, semantic mode and SHA256; never follow a symlink."""
    hasher, count, size = hashlib.sha256(), 0, 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not compiler and relative.parts[0] == ".git":
            continue
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if stat.S_ISLNK(info.st_mode):
            require(not compiler, "compiler contains a symlink")
            raw, mode = os.fsencode(os.readlink(path)), "120000"
        else:
            require(stat.S_ISREG(info.st_mode), "input tree contains a special file")
            raw = path.read_bytes()
            mode = "0755" if info.st_mode & 0o111 else "0644"
            if not compiler:
                mode = "100755" if info.st_mode & 0o111 else "100644"
        count, size = count + 1, size + len(raw)
        require(count <= 15_000 and size <= 300_000_000, "input tree exceeds its bound")
        hasher.update(
            relative.as_posix().encode()
            + b"\0"
            + mode.encode()
            + b"\0"
            + hashlib.sha256(raw).hexdigest().encode()
            + b"\n"
        )
    return {"sha256": hasher.hexdigest(), "files": count, "bytes": size}


def compiler_identity() -> tuple[Path, dict[str, Any]]:
    executable = shutil.which("go")
    require(executable is not None, "pinned Go compiler is unavailable")
    assert executable is not None
    compiler = Path(executable).resolve()
    require(digest(compiler) == GO_EXECUTABLE_SHA256, "Go executable digest differs")
    root = compiler.parent.parent
    inventory = tree_inventory(root, compiler=True)
    require(
        inventory
        == {
            "sha256": GO_TOOLCHAIN_SHA256,
            "files": GO_TOOLCHAIN_FILES,
            "bytes": GO_TOOLCHAIN_BYTES,
        },
        "complete Go toolchain differs from the pinned official distribution",
    )
    return compiler, {"executable_sha256": GO_EXECUTABLE_SHA256, "toolchain": inventory}


def source_identity(source: Path, stage: str) -> dict[str, Any]:
    inventory = tree_inventory(source)
    require(inventory["sha256"] == SOURCE_INVENTORIES[stage], "upstream source tree differs")
    for relative, expected in UNCHANGED_FILES.items():
        require(digest(source / relative) == expected, "default rules or module locks changed")
    return inventory
