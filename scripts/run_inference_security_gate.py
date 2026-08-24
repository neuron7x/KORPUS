#!/usr/bin/env python3
"""Execute the source-bound internal inference-security adversarial suite."""

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
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]
from korpus.application.junit_contracts import junit_counts  # noqa: E402
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
    zero = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if not path.is_file():
        return zero
    try:
        return junit_counts(ET.parse(path).getroot())
    except (ET.ParseError, OSError, ValueError):
        return {**zero, "failures": 1, "errors": 1}


def _normalized_mapping(profile: dict[str, Any]) -> dict[str, list[str]]:
    raw = profile.get("family_targets", {})
    if not isinstance(raw, dict):
        return {}
    return {
        str(family): [str(target) for target in targets]
        for family, targets in raw.items()
        if isinstance(targets, list)
    }


def _all_files(paths: list[str] | set[str]) -> bool:
    return bool(paths) and all((ROOT / path).is_file() for path in paths)


def _profile_checks(profile: dict[str, Any]) -> tuple[dict[str, bool], list[str], list[str]]:
    families = [str(item) for item in profile.get("attack_families", ())]
    targets = [str(item) for item in profile.get("pytest_targets", ())]
    mapping = _normalized_mapping(profile)
    mapped = {target for values in mapping.values() for target in values}
    checks = {
        "profile_gate_id": profile.get("gate_id") == "inference_security",
        "evidence_class_internal_adversarial": profile.get("evidence_class")
        == "INTERNAL_ADVERSARIAL",
        "attack_families_nonempty": bool(families),
        "attack_families_unique": len(families) == len(set(families)),
        "pytest_targets_nonempty": bool(targets),
        "pytest_targets_unique": len(targets) == len(set(targets)),
        "pytest_targets_exist": _all_files(targets),
        "family_target_mapping_complete": set(mapping) == set(families),
        "every_family_has_executable_target": bool(families) and all(map(mapping.get, families)),
        "family_targets_declared_in_suite": mapped == set(targets),
        "family_targets_exist": _all_files(mapped),
    }
    return checks, families, targets


def _execute(targets: list[str], junit: Path, timeout: int) -> tuple[int, str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--disable-warnings",
        f"--junitxml={junit}",
        *targets,
    ]
    try:
        run = subprocess.run(
            command,
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT / "apps/api/src")},
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return run.returncode, (run.stdout + run.stderr)[-8000:]
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout.decode(errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode(errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        return 124, (stdout + stderr)[-8000:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=PROFILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--junit", type=Path, default=DEFAULT_JUNIT)
    args = parser.parse_args()
    profile = _load_profile(args.profile)
    checks, families, targets = _profile_checks(profile)
    args.junit.parent.mkdir(parents=True, exist_ok=True)
    exit_code, output_tail = (None, "")
    if all(checks.values()):
        exit_code, output_tail = _execute(
            targets, args.junit, int(profile.get("timeout_seconds", 300) or 300)
        )
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
    result = gate_payload(
        "inference_security",
        status="PASS" if not failures else "FAIL",
        source_digest=compute_source_digest(ROOT),
        release=release_tag(),
        checks=checks,
        failures=failures,
        evidence_class="INTERNAL_ADVERSARIAL",
        profile=str(args.profile.relative_to(ROOT)),
        profile_sha256=hashlib.sha256(args.profile.read_bytes()).hexdigest()
        if args.profile.is_file()
        else None,
        attack_families=families,
        pytest_targets=targets,
        pytest_exit_code=exit_code,
        pytest=counts,
        junit_sha256=hashlib.sha256(args.junit.read_bytes()).hexdigest()
        if args.junit.is_file()
        else None,
        output_tail=output_tail,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
