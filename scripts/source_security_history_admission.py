"""Refuse Git history-boundary metadata that can hide reachable scanner inputs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts.source_security_contract import require
from scripts.trusted_system_tools import git_environment, git_executable


def require_complete_history_metadata(root: Path) -> None:
    git = git_executable()
    require(git is not None, "trusted Git executable unavailable")
    result = subprocess.run(
        [
            str(git),
            "--no-replace-objects",
            "-C",
            str(root),
            "rev-parse",
            "--is-shallow-repository",
            "--git-path",
            "shallow",
            "--git-path",
            "info/grafts",
            "--git-path",
            "info/attributes",
        ],
        env=git_environment(),
        capture_output=True,
        check=True,
        timeout=30,
    )
    paths = result.stdout.decode("utf-8").splitlines()
    require(len(paths) == 4 and paths[0] == "false", "shallow or unreadable Git history")
    require(
        all(not os.path.lexists(root / item) for item in paths[1:]),
        "shallow or grafted Git history or local attributes",
    )
