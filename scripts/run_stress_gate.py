#!/usr/bin/env python3
"""Bounded repeatability/fault stress gate for concurrency and degradation contracts."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]

from korpus.application.junit_contracts import junit_counts  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402

from scripts.release_identity import release_tag  # noqa: E402

POLICY = ROOT / "config/operations/test-adaptation-policy.json"
TESTS = (
    "apps/api/tests/test_reliability_degradation.py",
    "apps/api/tests/test_production_reliability.py",
    "apps/api/tests/test_durable_ingestion_jobs.py",
    "apps/api/tests/test_audit_anchor_semantics.py",
    "apps/api/tests/test_object_store_integrity.py",
    "apps/api/tests/test_s3_object_store.py",
    "apps/api/tests/test_plasticity_soak_v060.py",
)


def _counts(path: Path) -> tuple[int, int, int, int]:
    root = ET.parse(path).getroot()
    counts = junit_counts(root)
    return tuple(counts[name] for name in ("tests", "failures", "errors", "skipped"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/stress-gate.json")
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))["stress"]
    runs = []
    with tempfile.TemporaryDirectory(prefix="korpus-stress-") as tmp:
        for cycle in range(int(policy["cycles"])):
            junit = Path(tmp) / f"cycle-{cycle}.xml"
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = "0"
            env["PYTHONPATH"] = str(ROOT / "apps/api/src")
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--disable-warnings",
                    f"--junitxml={junit}",
                    *TESTS,
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
                check=False,
            )
            tests, failures, errors, skipped = _counts(junit) if junit.is_file() else (0, 1, 1, 0)
            runs.append(
                {
                    "cycle": cycle + 1,
                    "exit_code": proc.returncode,
                    "tests": tests,
                    "failures": failures,
                    "errors": errors,
                    "skipped": skipped,
                }
            )
    cardinalities = {(r["tests"], r["skipped"]) for r in runs}
    failures = []
    if policy.get("require_identical_test_cardinality") and len(cardinalities) != 1:
        failures.append("stress cycles did not execute identical test cardinality")
    if policy.get("require_zero_failures") and any(
        r["exit_code"] or r["failures"] or r["errors"] for r in runs
    ):
        failures.append("at least one stress cycle failed")
    report = {
        "schema": "korpus.stress-gate.v2",
        "status": "FAIL" if failures else "PASS",
        "release": release_tag(),
        "source_tree_sha256": compute_source_digest(ROOT),
        "runs": runs,
        "failures": failures,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
