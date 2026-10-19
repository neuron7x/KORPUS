from __future__ import annotations

import os
import stat
from pathlib import Path

GIT = "/usr/bin/git"
SSH_KEYGEN = "/usr/bin/ssh-keygen"


def trusted_executable(path: str) -> str | None:
    try:
        metadata = os.lstat(path)
    except OSError:
        return None
    safe = (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == 0
        and stat.S_IMODE(metadata.st_mode) & 0o022 == 0
        and os.access(path, os.X_OK)
    )
    return str(Path(path)) if safe else None


def git_executable() -> str | None:
    return trusted_executable(GIT)


def ssh_keygen_executable() -> str | None:
    return trusted_executable(SSH_KEYGEN)
