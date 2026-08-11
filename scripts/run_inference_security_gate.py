#!/usr/bin/env python3
"""Execute and bind the configured inference-security adversarial suite.

The gate is intentionally internal evidence: it proves that the configured
adversarial controls execute cleanly against the current source tree.  It does
not claim independent external red-team coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

PROFILE = ROOT / "config/assurance/inference-security-v1.json"
DEFAULT_OUT = ROOT / "var/production/inference_security-gate.json"
DEFAULT_JUNIT = ROOT / "var/production/inference_security.pytest.xml"


def _load_profile(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _suite_counts(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return {"tests": 0, "failures": 1, "errors": 1, "skipped": 0}
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        key: sum(int(float(suite.attrib.get(key, "0") or 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def _profile_checks(profile: dict[str, Any]) -> tuple[dict[str, bool], list[str], list[str]]:
    families = [str(item) for item in profile.get("attack_families", ())]
    targets = [str(item) for item in profile.get("pytest_targets", ())]
    checks = {
        "profile_gate_id": profile.get("gate_id") == "inference_security",
        "evidence_class_internal_adversarial": profile.get("evidence_class") == "INTERNAL_ADVERSARIAL",
        "attack_families_nonempty": bool(families),
        "attack_families_unique": len(families) == len(set(families)),
        "pytest_targets_nonempty": bool(targets),
        "pytest_targets_unique": len(targets) == len(set(targets)),
        "pytest_targets_exist": bool(targets) and all((ROOT / target).is_file() for target in targets),
    }
    return checks, families, targets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=PROFILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--junit", type=Path, default=DEFAULT_JUNIT)
    args = parser.parse_args()

    profile = _load_profile(args.profile)
    checks, families, targets = _profile_checks(profile)
    timeout_seconds = int(profile.get("timeout_seconds", 300) or 300)
    args.junit.parent.mkdir(parents=True, exist_ok=True)

    exit_code: int | None = None
    output_tail = ""
    if all(checks.values()):
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--disable-warnings",
            f"--junitxml={args.junit}",
            *targets,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT / "apps/api/src")},
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
            exit_code = completed.returncode
            output_tail = (completed.stdout + completed.stderr)[-8000:]
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            output_tail = (stdout + stderr)[-8000:]

    counts = _suite_counts(args.junit)
    checks.update(
        {
            "pytest_exit_zero": exit_code == 0,
            "tests_executed": counts["tests"] > 0,
            "no_test_failures": counts["failures"] == 0,
            "no_test_errors": counts["errors"] == 0,
            "no_test_skips": counts["skipped"] == 0,
        }
    )
    failures = [name for name, passed in checks.items() if not passed]
    source = compute_source_digest(ROOT)
    release = release_tag()
    result = gate_payload(
        "inference_security",
        status="PASS" if not failures else "FAIL",
        source_digest=source,
        release=release,
        checks=checks,
        failures=failures,
        evidence_class="INTERNAL_ADVERSARIAL",
        profile=str(args.profile.relative_to(ROOT)),
        profile_sha256=hashlib.sha256(args.profile.read_bytes()).hexdigest() if args.profile.is_file() else None,
        attack_families=families,
        pytest_targets=targets,
        pytest_exit_code=exit_code,
        pytest=counts,
        junit_sha256=hashlib.sha256(args.junit.read_bytes()).hexdigest() if args.junit.is_file() else None,
        output_tail=output_tail,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
