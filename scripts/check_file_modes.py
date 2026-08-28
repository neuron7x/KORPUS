#!/usr/bin/env python3
"""File permissions as a rule, over every tracked file rather than four directories.

Recorded modes had drifted to eight values across 2 011 tracked files — 660, 744, 750,
755, 760, 770, 664, 644 — none of them chosen. They are what umask, unzip and rsync left
behind, and `SOURCE_MANIFEST.json` had frozen that noise as intent: 192 of its entries
disagreed with the working tree, and the disagreement told a reader only which machine
had touched the file last.

The rule is the one this repository already enforces, not a new one:

    a file with a shebang is executable; a file without one is not.

Ruff states it as EXE001/EXE002 with five named exemptions, which is why picking any
other rule fails the lint: an earlier pass here normalised `*.sh` to 0755 and everything
else to 0644, and ruff immediately reported 151 Python entry points whose shebang no
longer matched their mode. That was the correct refusal.

What ruff cannot see is everything else. It reads `apps/api/src`, `apps/api/tests`,
`apps/api/migrations` and `scripts`, and only Python inside them — so the 23 shell
scripts, the Dockerfiles, the Terraform, the manifests and every file under `deploy/`,
`infra/`, `config/` and `evals/` had no mode check at all. This gate reads the same rule
over `git ls-files`, which is the set the source manifest hashes and the packager ships.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = 0o755
REGULAR = 0o644


def tracked_files() -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [name for name in listing.stdout.split("\0") if name]


def has_shebang(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


def main() -> int:
    violations: list[dict[str, str]] = []
    checked = 0
    executable = 0
    for name in tracked_files():
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            continue
        checked += 1
        expected = EXECUTABLE if has_shebang(path) else REGULAR
        executable += expected == EXECUTABLE
        actual = path.stat().st_mode & 0o777
        if actual != expected:
            violations.append(
                {
                    "path": name,
                    "actual": f"{actual:04o}",
                    "expected": f"{expected:04o}",
                    "reason": (
                        "a shebang declares the file is run directly"
                        if expected == EXECUTABLE
                        else "no shebang, so nothing runs this file directly"
                    ),
                }
            )

    report = {
        "schema": "korpus.file-mode-check.v1",
        "status": "FAIL" if violations else "PASS",
        "rule": "shebang => 0755, otherwise => 0644",
        "files_checked": checked,
        "executable_expected": executable,
        "violations": violations[:50],
        "violations_total": len(violations),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
