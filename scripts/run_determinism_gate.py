#!/usr/bin/env python3
"""Prove release-critical behavior is invariant across independent Python hash seeds."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]
from korpus.application.provenance import compute_source_digest  # noqa: E402
from korpus.application.determinism import failures, run_seed  # noqa: E402
from scripts.release_identity import release_tag  # noqa: E402

POLICY = ROOT / "config/operations/test-adaptation-policy.json"
TESTS = (
    "apps/api/tests/test_deterministic_branch_matrix_v050.py",
    "apps/api/tests/test_deterministic_plasticity_v060.py",
    "apps/api/tests/test_metamorphic_security_v060.py",
    "apps/api/tests/test_branch_cycle2_ratchet_v050.py",
    "apps/api/tests/test_release_state_machine.py",
    "apps/api/tests/test_assurance_calculus.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/determinism-gate.json")
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))["determinism"]
    with tempfile.TemporaryDirectory(prefix="korpus-determinism-") as tmp:
        runs = [run_seed(int(seed), Path(tmp) / f"seed-{seed}.xml", ROOT, TESTS)
                for seed in policy["python_hash_seeds"]]
    found = failures(runs, policy)
    report = {
        "schema": "korpus.determinism-gate.v2", "status": "FAIL" if found else "PASS",
        "release": release_tag(), "source_tree_sha256": compute_source_digest(ROOT),
        "runs": runs, "failures": found,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(found))


if __name__ == "__main__":
    raise SystemExit(main())
