#!/usr/bin/env python3
"""Install the declared API and web user services for the private pilot."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy/pilot"
TARGET = Path.home() / ".config/systemd/user"
UNITS = ("korpus-pilot-api.service", "korpus-pilot-web.service")


def render(name: str) -> str:
    value = (SOURCE / name).read_text(encoding="utf-8")
    return value.replace("@KORPUS_ROOT@", str(ROOT).replace("\\", "\\\\"))


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in UNITS:
        destination = TARGET / name
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(render(name), encoding="utf-8")
        os.replace(temporary, destination)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", *UNITS], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
