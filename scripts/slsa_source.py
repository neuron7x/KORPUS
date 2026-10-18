from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_MATERIALS = (
    "SOURCE_MANIFEST.json",
    "apps/api/src/korpus/release.json",
    "apps/api/requirements.runtime.lock",
    "apps/api/requirements.dev.lock",
    "apps/web/package-lock.json",
    "apps/api/Dockerfile",
    "apps/web/Dockerfile",
)


@dataclass(frozen=True)
class BuildInvocation:
    builder_id: str
    invocation_id: str
    started_on: str
    finished_on: str
    source_commit: str


def resolve_source_commit(root: Path, supplied: str) -> str:
    if supplied:
        return supplied
    return subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
