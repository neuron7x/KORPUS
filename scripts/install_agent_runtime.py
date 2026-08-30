#!/usr/bin/env python3
"""Install the bounded disposable-worktree runner used by all agent timers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy/agents/korpus-routine@.service"
TARGET = Path.home() / ".config/systemd/user/korpus-routine@.service"


def render() -> str:
    value = SOURCE.read_text(encoding="utf-8")
    return value.replace("@KORPUS_ROOT@", str(ROOT).replace("\\", "\\\\"))


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix(TARGET.suffix + ".tmp")
    temporary.write_text(render(), encoding="utf-8")
    os.replace(temporary, TARGET)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
