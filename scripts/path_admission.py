from __future__ import annotations

from pathlib import Path


def regular_file(path: Path) -> bool:
    """True only for a regular file reached without any symlink component."""
    absolute = path.absolute()
    return absolute.is_file() and not any(
        item.is_symlink() for item in (absolute, *absolute.parents)
    )
