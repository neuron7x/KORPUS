#!/usr/bin/env python3
"""Aggregate scanner success markers produced by their pinned CI images."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

EXPECTED = {"gitleaks", "pip-audit:runtime", "pip-audit:dev", "trivy"}


def _load(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("markers", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path("var/security/summary.json"))
    args = parser.parse_args()
    records: list[dict[str, object]] = []
    commits: set[str] = set()
    valid_shapes = True
    for path in args.markers:
        marker = _load(path)
        valid_shapes &= marker.get("schema") == "korpus.ci-scanner-result.v1"
        commit = str(marker.get("commit_sha", ""))
        if commit:
            commits.add(commit)
        scanners = marker.get("scanners", ())
        if not isinstance(scanners, list):
            valid_shapes = False
            continue
        records.extend(item for item in scanners if isinstance(item, dict))
    parsed = {str(item.get("scanner")): item.get("exit_code") for item in records}
    expected_commit = os.getenv("CI_COMMIT_SHA", "")
    checks = {
        "marker_shapes": valid_shapes,
        "scanner_set_exact": set(parsed) == EXPECTED and len(records) == len(EXPECTED),
        "all_scanners_zero": all(parsed.get(name) == 0 for name in EXPECTED),
        "single_commit": len(commits) == 1,
        "current_commit": not expected_commit or commits == {expected_commit},
    }
    failures = [name for name, ok in checks.items() if not ok]
    payload = {
        "schema_version": 2,
        "status": "PASS" if not failures else "FAIL",
        "commit_sha": next(iter(commits)) if len(commits) == 1 else "UNKNOWN",
        "scanners": sorted(records, key=lambda item: str(item.get("scanner"))),
        "worst_exit_code": max((int(item.get("exit_code", 127)) for item in records), default=127),
        "checks": checks,
        "failures": failures,
        "interpretation": "Aggregated only from scanner jobs that executed in their pinned CI images.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
