#!/usr/bin/env python3
"""Read back one completed canonical CI attempt without signing or production authority."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/api/src")]

from coverage.exceptions import CoverageException  # noqa: E402
from github_evidence_import import fetch_evidence  # noqa: E402
from github_evidence_result import HostedEvidence, json_bytes  # noqa: E402
from github_evidence_run import Selection  # noqa: E402


def write_evidence(evidence: HostedEvidence, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for artifact in evidence.artifacts:
        (destination / f"artifact-{artifact.artifact_id}.zip").write_bytes(artifact.zip_bytes)
    (destination / "coverage-union.json").write_bytes(evidence.coverage_bytes)
    (destination / "github-evidence-admission.json").write_bytes(json_bytes(evidence.receipt))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--ref", default="refs/heads/main")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    # A failed live readback cannot leave a previous admission receipt looking current.
    for name in ("github-evidence-admission.json", "coverage-union.json"):
        (args.out / name).unlink(missing_ok=True)
    try:
        selected = Selection(args.run_id, args.run_attempt, args.ref)
        evidence = fetch_evidence(args.source_root, selected)
        write_evidence(evidence, args.out)
    except (OSError, ValueError, CoverageException) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error), "production_authorized": False}))
        return 1
    print(json_bytes(evidence.receipt).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
