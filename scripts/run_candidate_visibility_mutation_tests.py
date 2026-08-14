#!/usr/bin/env python3
"""Targeted mutation gate for bounded candidate-admission equivalence (#27)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "var/candidate-visibility-mutation-report.json"
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from candidate_visibility_mutants import MUTANTS, Mutant  # noqa: E402
from korpus.application.provenance import stamp  # noqa: E402


def _python() -> str:
    requested = os.getenv("PYTHON", "")
    if not requested:
        return sys.executable
    found = shutil.which(requested)
    if found:
        return found
    candidate = (ROOT / requested).resolve()
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError(f"PYTHON executable not found: {requested}")


def _environment(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "apps/api/src")))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run(root: Path, selector: str, python: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [python, "-m", "pytest", selector, "-q"],
        cwd=root,
        env=_environment(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _copy_tree(target: Path) -> None:
    shutil.copytree(
        ROOT,
        target,
        ignore=shutil.ignore_patterns(
            ".git",
            "var",
            ".venv",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        ),
    )


def _mutate(work: Path, mutant: Mutant) -> None:
    path = work / mutant.path
    source = path.read_text(encoding="utf-8")
    count = source.count(mutant.old)
    if count != mutant.replacements:
        raise RuntimeError(
            f"{mutant.id}: expected {mutant.replacements} mutation sites in "
            f"{mutant.path}, found {count}"
        )
    path.write_text(source.replace(mutant.old, mutant.new), encoding="utf-8")


def main() -> int:
    python = _python()
    selectors = sorted({mutant.control for mutant in MUTANTS})
    controls: dict[str, dict[str, object]] = {}
    invalid: list[str] = []
    for selector in selectors:
        result = _run(ROOT, selector, python)
        controls[selector] = {
            "returncode": result.returncode,
            "output_tail": result.stdout[-2000:],
        }
        if result.returncode != 0:
            invalid.append(f"control failed: {selector}")

    outcomes: list[dict[str, object]] = []
    if not invalid:
        for mutant in MUTANTS:
            with tempfile.TemporaryDirectory(prefix=f"korpus-{mutant.id.lower()}-") as tmp:
                work = Path(tmp) / "repo"
                _copy_tree(work)
                try:
                    _mutate(work, mutant)
                except RuntimeError as exc:
                    invalid.append(str(exc))
                    outcomes.append({**asdict(mutant), "status": "INVALID", "returncode": None})
                    continue
                result = _run(work, mutant.control, python)
                outcomes.append(
                    {
                        **asdict(mutant),
                        "status": "KILLED" if result.returncode != 0 else "SURVIVED",
                        "returncode": result.returncode,
                        "output_tail": result.stdout[-2000:],
                    }
                )

    killed = sum(item.get("status") == "KILLED" for item in outcomes)
    survived = [str(item["id"]) for item in outcomes if item.get("status") == "SURVIVED"]
    report = {
        "schema": "korpus.candidate-visibility-mutation.v1",
        "provenance": stamp(ROOT, "scripts/run_candidate_visibility_mutation_tests.py"),
        "catalogue_provenance": stamp(ROOT, "scripts/candidate_visibility_mutants.py"),
        "mutants": len(MUTANTS),
        "executed_mutants": len(outcomes),
        "killed": killed,
        "survived": survived,
        "invalid": invalid,
        "controls": controls,
        "outcomes": outcomes,
        "status": "PASS"
        if not invalid and not survived and killed == len(MUTANTS)
        else "FAIL",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
