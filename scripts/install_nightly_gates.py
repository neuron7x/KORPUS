#!/usr/bin/env python3
"""Поставити нічний лан гейтів для поточного шляху дерева.

Окремий інсталятор, а не запис у `install_public_runtime`: там `UNITS` описують
ПУБЛІЧНИЙ рантайм, і його тест вимагає від кожного юніта посилання на файл JWT-секрета.
Нічний лан секретів не потребує, і додати його туди означало б послабити той тест.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy/agents"
TARGET = Path.home() / ".config/systemd/user"
UNITS = ("korpus-nightly-gates.service", "korpus-nightly-gates.timer")


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
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", "korpus-nightly-gates.timer"], check=True
    )
    print(f"nightly gate lane installed for {ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
