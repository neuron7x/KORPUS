"""Stage verified ZIP members on the destination filesystem before atomic publication."""

from __future__ import annotations

import os
import stat
import tempfile
import zipfile
from pathlib import Path


def _require_replaceable(target: Path) -> None:
    # Overwriting populated destinations cannot be made portable and failure-atomic.
    if target.is_symlink() or (target.exists() and
                               (not target.is_dir() or any(target.iterdir()))):
        raise FileExistsError(f"archive destination must be absent or empty: {target}")


def _extract_staged(zf: zipfile.ZipFile, staged: Path) -> None:
    zf.extractall(staged)
    for info in zf.infolist():
        if not info.is_dir():
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                os.chmod(staged / info.filename, mode)
    if not any(staged.iterdir()):
        raise ValueError("empty archive cannot be published")


def publish_safe_zip(zf: zipfile.ZipFile, destination: Path) -> Path:
    target = Path(destination)
    _require_replaceable(target)
    # A sibling stage forces the final rename to remain on one filesystem.
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.staging-",
                                     dir=target.parent) as staging_name:
        staged = Path(staging_name)
        _extract_staged(zf, staged)
        _require_replaceable(target)
        mode = stat.S_IMODE(target.stat().st_mode) if target.is_dir() else 0o700
        staged.chmod(mode)
        os.replace(staged, target)
    return next(target.iterdir())
