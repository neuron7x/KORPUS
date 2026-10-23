from __future__ import annotations

import stat
from pathlib import Path

SOURCE_ROOT_MARKER = ".korpus-source-root"
SOURCE_ROOT_MARKER_BYTES = (
    b"korpus.canonical-source-root.v1\nrepository=neuron7x/KORPUS\npackage_included=false\n"
)


def marker_matches(root: Path) -> bool:
    path = root / SOURCE_ROOT_MARKER
    try:
        metadata = path.lstat()
        return (
            stat.S_ISREG(metadata.st_mode)
            and stat.S_IMODE(metadata.st_mode) & 0o7111 == 0
            and path.read_bytes() == SOURCE_ROOT_MARKER_BYTES
        )
    except (OSError, UnicodeError, ValueError):
        return False
