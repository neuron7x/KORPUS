#!/usr/bin/env python3
"""Execute ruff and mypy and leave an artifact proving they ran.

Until 2026-08-04 the assurance report carried the string
``"ruff": "NOT_EXECUTED_LOCAL_PACKAGE_UNAVAILABLE; REQUIRED_IN_GITLAB"`` next to
``"status": "PASS"``. The CI job did run both tools, but nothing downstream could
tell a green run from a run that never happened — the aggregate verdict was the
same either way. This writes the run itself down: command, exit code, violation
count, and the source tree the run applies to.

mypy runs twice, over two configurations, because one file could not describe both. The
application is checked with apps/api/pyproject.toml, whose `packages = ["korpus"]` also
means it type-checked nothing else: every runner, gate and generator under scripts/ — the
code that decides whether a release is admissible — was unchecked until 2026-08-29, and the
first run of mypy-scripts.ini over it found 198 errors in 58 files.

`ruff format --check` is here because formatting drift is not cosmetic in this repository.
The mutation catalogue and several gate-parity tests match on exact source lines; when 62
files were finally formatted, 18 mutants and 2 tests silently lost their targets, and a
mutant whose target string is absent is a mutant that cannot fail. Held as a check, the
tree cannot drift out of canonical form and take the mutation evidence with it. Migrations
are excluded: an applied migration is pinned by digest as an immutable baseline, and
reformatting one reads to that gate as a mutated migration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.provenance import PROVENANCE_KEY, stamp  # noqa: E402  (path set above)

RUFF = [
    sys.executable,
    "-m",
    "ruff",
    "check",
    "--output-format",
    "json",
    "apps/api/src",
    "apps/api/tests",
    "apps/api/migrations",
    "scripts",
]
# apps/api/migrations is deliberately absent. An applied migration is an immutable
# artifact: check_gcp_migration_compatibility.py pins every baseline file by digest and
# reports "baseline migration mutated" for any change at all, formatting included. The two
# rules would fight, and the migration rule is the one that protects a deployed database.
RUFF_FORMAT = [
    sys.executable,
    "-m",
    "ruff",
    "format",
    "--check",
    "apps/api/src",
    "apps/api/tests",
    "scripts",
]
#: `--cache-dir` у var/, як і для scripts/: кеш усередині дерева вміє відмивати гейти —
#: `scripts/.mypy_cache` містить імена всіх модулів і зробив зеленим тест досяжності
#: скриптів. Прибрати причину дешевше, ніж вести список винятків.
MYPY = [
    sys.executable,
    "-m",
    "mypy",
    "--config-file",
    "apps/api/pyproject.toml",
    "--cache-dir",
    "var/mypy-cache-api",
]
#: Run from INSIDE scripts/, not from the repository root, and this is the whole point of
#: the entry. With `mypy … scripts/` from the root, mypy resolved every intra-scripts
#: import as `Any`: `from manifest_paths import source_paths` type-checked to nothing, and
#: so did every other sibling import in the directory. The gate reported PASS over 217
#: files while the contracts BETWEEN them were unchecked. Measured 2026-08-30 by running
#: it the other way: 7 errors appeared at once, two of them real — `str | None` passed
#: where `str` was declared in the replay CLI, and `int | None` from a timed-out
#: subprocess handed to a function typed `int` in the mutation runner.
#:
#: The base directory decides the module names. From the root, `scripts/gcp/x.py` is
#: `scripts.gcp.x` and `mypy_path` cannot also contain scripts/ without the same file
#: acquiring two names and mypy refusing to start. From inside, it is `gcp.x`, siblings
#: are top-level modules, and the application still resolves through MYPYPATH.
#: `--cache-dir` поза scripts/ — інакше mypy лишає там `.mypy_cache`, і той кеш містить
#: імена всіх модулів. `test_every_script_is_reachable_from_a_runner` шукає згадки скрипта
#: серед файлів scripts/ і після одного прогону mypy визнавав досяжним КОЖЕН скрипт.
#: Тобто виправлення типізації мовчки вимкнуло сусідній гейт. Виявлено 2026-08-30 у
#: чистому клоні: там кешу немає, і тест упав на скрипті, якого справді ніхто не кличе.
MYPY_SCRIPTS = [
    sys.executable,
    "-m",
    "mypy",
    "--config-file",
    "../mypy-scripts.ini",
    "--cache-dir",
    "../var/mypy-cache-scripts",
    ".",
]
SCRIPTS_DIR = ROOT / "scripts"


def _run(
    command: list[str],
    env_extra: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(env_extra or {})
    return subprocess.run(
        command,
        cwd=cwd or ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _ruff_result() -> dict[str, object]:
    completed = _run(RUFF)
    try:
        violations = json.loads(completed.stdout or "[]")
        violation_count = len(violations) if isinstance(violations, list) else -1
    except json.JSONDecodeError:
        # ruff failing to start is not zero violations; a count that cannot be
        # read must not be reported as clean.
        violation_count = -1
    return {
        "command": " ".join(RUFF),
        "exit_code": completed.returncode,
        "violations": violation_count,
        "status": "PASS" if completed.returncode == 0 and violation_count == 0 else "FAIL",
        "output_tail": completed.stdout[-2000:],
    }


def _ruff_format_result() -> dict[str, object]:
    """Canonical formatting, held as a gate because the mutation catalogue depends on it."""
    completed = _run(RUFF_FORMAT)
    return {
        "command": " ".join(RUFF_FORMAT),
        "exit_code": completed.returncode,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "output_tail": completed.stdout[-2000:],
    }


def _mypy_result() -> dict[str, object]:
    completed = _run(MYPY, {"MYPYPATH": str(ROOT / "apps/api/src")})
    return {
        "command": " ".join(MYPY),
        "exit_code": completed.returncode,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "output_tail": completed.stdout[-2000:],
    }


def _mypy_scripts_result() -> dict[str, object]:
    """The second configuration: scripts/, which the application's config excludes."""
    completed = _run(MYPY_SCRIPTS, {"MYPYPATH": str(ROOT / "apps/api/src")}, cwd=SCRIPTS_DIR)
    return {
        "command": " ".join(MYPY_SCRIPTS),
        "exit_code": completed.returncode,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "output_tail": completed.stdout[-2000:],
    }


def main() -> int:
    tools = {
        "ruff": _ruff_result(),
        "ruff_format": _ruff_format_result(),
        "mypy": _mypy_result(),
        "mypy_scripts": _mypy_scripts_result(),
    }
    report = {
        "schema_version": 1,
        "status": "PASS" if all(tool["status"] == "PASS" for tool in tools.values()) else "FAIL",
        "tools": tools,
        PROVENANCE_KEY: stamp(ROOT, "scripts/run_quality_gate.py"),
    }
    output = ROOT / "var/quality-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "ruff": {k: v for k, v in tools["ruff"].items() if k != "output_tail"},
                "ruff_format": {
                    k: v for k, v in tools["ruff_format"].items() if k != "output_tail"
                },
                "mypy": {k: v for k, v in tools["mypy"].items() if k != "output_tail"},
                "mypy_scripts": {
                    k: v for k, v in tools["mypy_scripts"].items() if k != "output_tail"
                },
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
