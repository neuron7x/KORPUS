#!/usr/bin/env python3
"""Install the declared API and web user services for the private pilot."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy/pilot"
TARGET = Path.home() / ".config/systemd/user"
UNITS = ("korpus-pilot-api.service", "korpus-pilot-web.service")

# Absolute path; systemd rejects quotes, backslashes and controls in executables.
# Reject dollars (environment expansion) and trailing whitespace (raw path trim).
SUPPORTED_ROOT = re.compile(r"""/[^\x00-\x1f\x7f\ud800-\udfff\\"'$]*(?<!\s)""")


def render(name: str) -> str:
    if name not in UNITS:
        raise ValueError(f"Unknown pilot unit: {name!r}")
    root = str(ROOT)
    if not SUPPORTED_ROOT.fullmatch(root):
        raise ValueError("Workspace path cannot be represented safely in pilot units")
    value = (SOURCE / name).read_text(encoding="utf-8")
    # Escape only the substituted path, retaining intentional unit specifiers.
    return value.replace("@KORPUS_ROOT@", root.replace("%", "%%"))


def main() -> int:
    rendered = {name: render(name) for name in UNITS}
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in UNITS:
        destination = TARGET / name
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(rendered[name], encoding="utf-8")
        os.replace(temporary, destination)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", *UNITS], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
