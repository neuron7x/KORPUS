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
EXECUTABLE_BIT = 0o111


def tracked_files() -> list[str]:
    """The set git tracks — or a refusal, never a traceback.

    An unpacked release archive has no .git, and `git ls-files` there exits 128. The check
    used to raise CalledProcessError, so the caller saw a Python traceback on stderr and no
    JSON on stdout: a gate that cannot say what it found is indistinguishable from one that
    crashed for an unrelated reason. It reports the condition and exits non-zero instead.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if listing.returncode != 0:
        raise NotAGitCheckout(listing.stderr.strip() or "git ls-files failed")
    return [name for name in listing.stdout.split("\0") if name]


class NotAGitCheckout(RuntimeError):
    """This tree is not a Git checkout, so there is no tracked set to check."""


def has_shebang(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


def _violation(name: str, should_execute: bool) -> dict[str, str]:
    return {
        "path": name,
        "actual": "not executable" if should_execute else "executable",
        "expected": "executable" if should_execute else "not executable",
        "reason": (
            "a shebang declares the file is run directly"
            if should_execute
            else "no shebang, so nothing runs this file directly"
        ),
    }


def main() -> int:
    violations: list[dict[str, str]] = []
    checked = 0
    executable = 0
    try:
        names = tracked_files()
    except NotAGitCheckout as exc:
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "not a Git checkout; the file-mode rule is defined over the "
                    "tracked set and there is none here",
                    "detail": str(exc),
                    "files_checked": 0,
                    "violations": [],
                },
                indent=2,
            )
        )
        return 2
    for name in names:
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            continue
        checked += 1
        should_execute = has_shebang(path)
        executable += should_execute
        if bool(path.stat().st_mode & EXECUTABLE_BIT) != should_execute:
            violations.append(_violation(name, should_execute))

    report = {
        "schema": "korpus.file-mode-check.v2",
        "status": "FAIL" if violations else "PASS",
        "rule": "shebang <=> executable bit; read and write bits are the runner's umask",
        "files_checked": checked,
        "executable_expected": executable,
        "violations": violations[:50],
        "violations_total": len(violations),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
