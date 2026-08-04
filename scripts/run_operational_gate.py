#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from korpus.application.operations import OperationalReleaseGate
from korpus.application.provenance import compute_source_digest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config/operations/reference-v5.json"
REPORT_PATHS = {
    "eval": ROOT / "var/eval-report.json",
    "mutation": ROOT / "var/mutation-report.json",
    "migration": ROOT / "var/migration-report.json",
    "scale": ROOT / "var/scale-report.json",
}


def main() -> int:
    missing = [str(path) for path in REPORT_PATHS.values() if not path.is_file()]
    if missing:
        print(json.dumps({"status": "FAIL", "missing": missing}, indent=2))
        return 1
    reports = {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in REPORT_PATHS.items()
    }
    # Recomputed here, never read from the artifacts: a digest the reports supply
    # would only prove they agree with themselves.
    result = OperationalReleaseGate.load(POLICY).evaluate(
        reports, REPORT_PATHS, source_digest=compute_source_digest(ROOT)
    )
    output = ROOT / "var/operational-gate.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
