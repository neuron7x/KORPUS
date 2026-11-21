#!/usr/bin/env python3
"""Wait for independent CI, then perform fresh full-subject evidence admission."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/api/src")]

from coverage.exceptions import CoverageException  # noqa: E402
from github_evidence_import import fetch_evidence  # noqa: E402
from github_evidence_result import json_bytes  # noqa: E402
from github_evidence_wait import MAX_WAIT_SECONDS, wait_for_selection  # noqa: E402
from import_github_evidence import write_evidence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--timeout", type=int, default=MAX_WAIT_SECONDS)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name in ("github-evidence-admission.json", "coverage-union.json"):
        (args.out / name).unlink(missing_ok=True)
    try:
        selected = wait_for_selection(args.source_root, args.ref, args.timeout)
        evidence = fetch_evidence(args.source_root, selected)
        write_evidence(evidence, args.out)
    except (OSError, ValueError, CoverageException) as error:
        diagnostic = {"status": "FAIL", "reason": str(error), "production_authorized": False}
        (args.out / "readback-diagnostic.json").write_bytes(json_bytes(diagnostic))
        print(json.dumps(diagnostic))
        return 1
    print(json_bytes(evidence.receipt).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
