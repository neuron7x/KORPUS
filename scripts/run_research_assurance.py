#!/usr/bin/env python3
"""Run the reproducible local assurance stack and aggregate machine-readable evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "var"

#: ВЛАСНЕ ім'я, і це не оформлення. Доти цей скрипт писав
#: `var/research-assurance-report.json` — той самий шлях, що й `assemble_assurance.py`,
#: але БЕЗ ярликованих дайджестів (`digest_scope`, `evidence_source_sha256`,
#: `tracked_tree_scope`, `tracked_tree_sha256`), які читають усі споживачі. Хто біг
#: останній, той і визначав, чи доказ прив'язаний.
#:
#: Найгірша форма цього: `verify_handoff_contract` у відмові радить «Run `make assurance
#: operational-gate` against this revision» — а `make assurance` кличе саме цей скрипт і
#: ЗАТИРАЄ доказ, якого тій відмові бракувало. Виконання поради гарантувало відмову.
#: Тому `release_evidence: STALE` при `status: PASS` тримався роками. Виміряно 03.09.2026.
OUTPUT = VAR / "research-assurance-run.json"
VAR.mkdir(exist_ok=True)


def run(name: str, command: list[str], env: dict[str, str] | None = None) -> dict[str, object]:
    started = time.perf_counter()
    output_path = VAR / f"assurance-{name}.log"
    with output_path.open("w", encoding="utf-8") as output_handle:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=output_handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return {
        "name": name,
        "command": command,
        "returncode": completed.returncode,
        "duration_seconds": time.perf_counter() - started,
        "log": str(output_path.relative_to(ROOT)),
    }


def load_json(path: Path) -> object | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def main() -> int:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "apps/api/src")
    steps = [
        run("openapi", [sys.executable, "scripts/openapi_contract.py"], environment),
        run(
            "desired-state",
            [sys.executable, "scripts/generate_desired_state.py", "--check"],
            environment,
        ),
        run(
            "supply-chain-inventory",
            [sys.executable, "scripts/generate_supply_chain_inventory.py"],
            environment,
        ),
        run("repository", [sys.executable, "scripts/validate_repository.py"], environment),
        run("infrastructure", [sys.executable, "scripts/validate_infrastructure.py"], environment),
        run("kubernetes", [sys.executable, "scripts/validate_kubernetes.py"], environment),
        run(
            "compile",
            [
                sys.executable,
                "-m",
                "compileall",
                "-q",
                "apps/api/src",
                "apps/api/migrations",
                "scripts",
            ],
            environment,
        ),
    ]
    parallel_commands = [
        (
            "pytest",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "apps/api/tests",
                "--junitxml=var/pytest.xml",
                "--cov=apps/api/src/korpus",
                "--cov-branch",
                "--cov-report=xml:var/coverage.xml",
                "--cov-report=json:var/coverage.json",
                "--cov-fail-under=82",
            ],
        ),
        ("eval", [sys.executable, "scripts/run_evals.py"]),
        ("migration", [sys.executable, "scripts/run_migration_gate.py"]),
        ("scale", [sys.executable, "scripts/run_scale_probe.py"]),
        ("web", ["npm", "--prefix", "apps/web", "run", "build"]),
    ]
    with ThreadPoolExecutor(max_workers=len(parallel_commands)) as pool:
        futures = [
            pool.submit(run, name, command, environment) for name, command in parallel_commands
        ]
        steps.extend(future.result() for future in futures)
    if all(step["returncode"] == 0 for step in steps):
        mutation_environment = environment.copy()
        mutation_environment["PYTHON"] = sys.executable
        mutation_environment["KORPUS_MUTATION_SHARDS"] = "6"
        steps.append(
            run(
                "mutation",
                ["bash", "scripts/run_mutation_shards.sh"],
                mutation_environment,
            )
        )
    # audit-closure resolves every citation in the closure registry, and COD-005 cites
    # var/mutation-report.json. It used to be the second step of this run, before the
    # mutation shards existed — so it read whatever a previous run had left in var/,
    # or failed outright on a clean tree. It belongs after its producer.
    if all(step["returncode"] == 0 for step in steps):
        steps.append(
            run("audit-closure", [sys.executable, "scripts/build_audit_closure.py"], environment)
        )
    if all(step["returncode"] == 0 for step in steps):
        steps.append(
            run("operational", [sys.executable, "scripts/run_operational_gate.py"], environment)
        )
    test_summary: dict[str, object] = {}
    junit_path = VAR / "pytest.xml"
    if junit_path.is_file():
        root = ET.parse(junit_path).getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        if suite is not None:
            test_summary = {
                key: suite.attrib.get(key, "0")
                for key in ("tests", "failures", "errors", "skipped", "time")
            }
    coverage_summary: dict[str, object] = {}
    coverage_path = VAR / "coverage.xml"
    if coverage_path.is_file():
        coverage = ET.parse(coverage_path).getroot()
        coverage_summary = {
            "line_rate": float(coverage.attrib.get("line-rate", "0")),
            "branch_rate": float(coverage.attrib.get("branch-rate", "0")),
        }
    report = {
        "schema_version": 2,
        "status": "PASS" if all(step["returncode"] == 0 for step in steps) else "FAIL",
        "steps": steps,
        "pytest": test_summary,
        "coverage": coverage_summary,
        "eval": load_json(VAR / "eval-report.json"),
        "mutation": load_json(VAR / "mutation-report.json"),
        "migration": load_json(VAR / "migration-report.json"),
        "scale": load_json(VAR / "scale-report.json"),
        "operational": load_json(VAR / "operational-gate.json"),
        "limitations": [
            (
                "Ruff and mypy are separate CI gates and are not claimed unless "
                "executed in the current environment."
            ),
            (
                "PostgreSQL integration is a dedicated CI service-container gate; "
                "local report may show it skipped."
            ),
            "Synthetic evaluation does not authorize real restricted corpus deployment.",
        ],
    }
    output = OUTPUT
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "status": report["status"],
        "pytest": test_summary,
        "coverage": coverage_summary,
    }
    print(json.dumps(summary, indent=2))
    for step in steps:
        print(
            f"{step['name']}: rc={step['returncode']} "
            f"{step['duration_seconds']:.2f}s -> {step['log']}"
        )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
