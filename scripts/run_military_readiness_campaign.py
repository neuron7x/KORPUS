#!/usr/bin/env python3
"""Run source-local military readiness checks without conflating execution with admission.

The baseline checks are fast. Full backend regression is executed as deterministic,
disjoint test-module batches: one monolithic pytest process turned a timeout into an
unlocalised UNKNOWN after most of the suite had already passed. Batch isolation keeps
the test surface unchanged while making completion, timeout and failure attributable.

This runner never converts external TEVV/production obligations into PASS.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / "apps/api/tests"

BASELINE = [
    ("current_truth", [sys.executable, "scripts/verify_current_truth.py"]),
    ("package_identity", [sys.executable, "scripts/verify_package_build_identity.py"]),
    (
        "module_ratchet",
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "apps/api/tests/test_branch_cycle2_ratchet_v050.py",
        ],
    ),
    (
        "evaluation_validity",
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "apps/api/tests/test_evaluation_validity.py",
        ],
    ),
    (
        "military_assurance",
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "apps/api/tests/test_military_assurance.py",
            "apps/api/tests/test_military_knowledge.py",
        ],
    ),
    (
        "tevv_boundaries",
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "apps/api/tests/test_tevv_admissibility.py",
            "apps/api/tests/test_tevv_attestation_boundary.py",
            "apps/api/tests/test_tevv_ledger_boundary.py",
        ],
    ),
]


def regression_batches(batch_size: int) -> list[tuple[str, list[str]]]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    files = sorted(TEST_ROOT.glob("test_*.py"), key=lambda path: path.name)
    batches: list[tuple[str, list[str]]] = []
    for index in range(0, len(files), batch_size):
        group = files[index : index + batch_size]
        argv = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *[path.relative_to(ROOT).as_posix() for path in group],
        ]
        batches.append((f"backend_regression_{index // batch_size:03d}", argv))
    return batches


def run_one(name: str, argv: list[str], timeout: int) -> dict[str, object]:
    started = time.monotonic()
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", "apps/api/src:.")
    try:
        cp = subprocess.run(
            argv,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "name": name,
            "status": "PASS" if cp.returncode == 0 else "FAIL",
            "returncode": cp.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "command": argv,
            "stdout_tail": cp.stdout[-8000:],
            "stderr_tail": cp.stderr[-8000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "status": "UNKNOWN",
            "returncode": None,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "command": argv,
            "stdout_tail": (exc.stdout or "")[-8000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-8000:] if isinstance(exc.stderr, str) else "",
            "reason": "timeout",
        }


def run_parallel(
    checks: list[tuple[str, list[str]]], timeout: int, workers: int
) -> list[dict[str, object]]:
    if workers < 1:
        raise ValueError("workers must be positive")
    results: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, name, argv, timeout): name for name, argv in checks}
        for future in as_completed(futures):
            result = future.result()
            results[str(result["name"])] = result
    return [results[name] for name, _ in checks]


def aggregate_status(results: list[dict[str, object]]) -> str:
    statuses = {str(result["status"]) for result in results}
    if "FAIL" in statuses:
        return "FAIL"
    if "UNKNOWN" in statuses:
        return "UNKNOWN"
    return "PASS"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full", action="store_true", help="execute the complete backend regression surface"
    )
    parser.add_argument("--timeout", type=int, default=180, help="seconds per baseline check")
    parser.add_argument(
        "--full-timeout", type=int, default=180, help="seconds per regression batch"
    )
    parser.add_argument("--regression-batch-size", type=int, default=8)
    parser.add_argument("--regression-workers", type=int, default=2)
    parser.add_argument("--output", default="reports/MILITARY_READINESS_CAMPAIGN_CURRENT.json")
    args = parser.parse_args()

    baseline = [run_one(name, argv, args.timeout) for name, argv in BASELINE]
    regression_commands = regression_batches(args.regression_batch_size) if args.full else []
    regression = (
        run_parallel(
            regression_commands,
            args.full_timeout,
            args.regression_workers,
        )
        if regression_commands
        else []
    )
    results = [*baseline, *regression]
    report = {
        "schema": "korpus.military-readiness-campaign.v2",
        "scope": "full" if args.full else "bounded",
        "status": aggregate_status(results),
        "results": results,
        "regression": {
            "test_modules": len(list(TEST_ROOT.glob("test_*.py"))),
            "batches": len(regression_commands),
            "batch_size": args.regression_batch_size if args.full else None,
            "workers": args.regression_workers if args.full else None,
            "status": aggregate_status(regression) if regression else "NOT_EXECUTED",
        },
        "production_authorized": False,
        "production_authorization_note": (
            "Software execution cannot substitute for real-domain, independent, human-system, "
            "live-RLS, load/DR or trusted-signing evidence."
        ),
    }
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
