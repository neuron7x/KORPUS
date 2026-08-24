#!/usr/bin/env python3
"""Write the current production verdict for diagnostics without promoting it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/PRODUCTION_ASSURANCE_REPORT.json"


def main() -> int:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/assemble_production_assurance.py")],
        cwd=ROOT,
        check=False,
    )
    if not REPORT.is_file() or completed.returncode not in {0, 1}:
        return 1
    try:
        report = json.loads(REPORT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1
    passed = report.get("status") == "PASS" and report.get("production_authorized") is True
    failed = report.get("status") == "FAIL" and report.get("production_authorized") is False
    if not (passed or failed) or (completed.returncode == 0) != passed:
        return 1
    print(json.dumps({"status": report["status"], "production_authorized": passed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
