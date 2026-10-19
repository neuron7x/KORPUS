#!/usr/bin/env python3
"""Publish source-bound web lint, test, build, and exact TAP evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.provenance import stamp  # noqa: E402
from release_identity import release_tag  # noqa: E402

OUT = ROOT / "var/web-regression.json"
STEPS = ("lint", "test", "build")


def _run(script: str) -> tuple[int, bytes]:
    done = subprocess.run(
        ["npm", "--prefix", "apps/web", "run", script],
        cwd=str(ROOT),
        capture_output=True,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def _tap_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in ("tests", "pass", "fail", "skipped"):
        found = re.search(rf"^# {key} (\d+)$", text, re.MULTILINE)
        if found:
            counts[key] = int(found.group(1))
    return counts


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--tap-out", type=Path, default=None, help="write exact fresh node --test output"
    )
    return parser.parse_args(argv)


def _execute() -> tuple[dict[str, Any], bytes]:
    results: dict[str, Any] = {}
    test_output = b""
    for script in STEPS:
        code, output = _run(script)
        results[script] = {"exit_code": code, "status": "PASS" if code == 0 else "FAIL"}
        if script == "test":
            test_output = output
            results[script].update(_tap_counts(output.decode("utf-8", errors="replace")))
    return results, test_output


def _payload(execution: tuple[dict[str, Any], bytes]) -> tuple[dict[str, Any], bool]:
    results, test_output = execution
    counts = results["test"]
    executed = counts.get("tests")
    healthy = (
        all(step["exit_code"] == 0 for step in results.values())
        and isinstance(executed, int)
        and executed > 0
        and counts.get("fail") == 0
    )
    report = {
        "schema": "korpus.web-regression.v1",
        "release": release_tag(ROOT),
        "status": "PASS" if healthy else "FAIL",
        "steps": results,
        "tests": executed,
        "passed": counts.get("pass"),
        "failed": counts.get("fail"),
        "skipped": counts.get("skipped"),
        "test_output_sha256": hashlib.sha256(test_output).hexdigest(),
        "evidence_class": "LOCAL_NODE_TEST_RUNNER",
        "provenance": stamp(ROOT, "scripts/publish_web_regression.py"),
    }
    return report, healthy


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    execution = _execute()
    report, healthy = _payload(execution)
    test_output = execution[1]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.tap_out is not None:
        args.tap_out.parent.mkdir(parents=True, exist_ok=True)
        args.tap_out.write_bytes(test_output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
