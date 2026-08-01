#!/usr/bin/env python3
"""Repeat deterministic assurance producers and compare complete artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "var/determinism/determinism-assurance.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable(hashes: list[str], repetitions: int) -> bool:
    return len(hashes) == repetitions and repetitions >= 2 and len(set(hashes)) == 1


def validate_report(report: dict[str, Any]) -> None:
    required = {"schema", "candidate_commit", "repetitions", "artifacts", "environment",
                "production_authorized", "verdict"}
    if set(report) != required:
        raise ValueError("DET-REPORT-FIELDS")
    if report["production_authorized"] is not False:
        raise ValueError("DET-PRODUCTION-AUTHORIZATION")
    if report["verdict"] not in {"PASS", "FAIL"}:
        raise ValueError("DET-VERDICT")
    repetitions = report["repetitions"]
    if not isinstance(repetitions, int) or repetitions < 2:
        raise ValueError("DET-REPETITIONS")
    artifacts = report["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != {"eval_report", "system_manifest"}:
        raise ValueError("DET-ARTIFACTS")
    predicates = []
    for name, record in artifacts.items():
        hashes = record.get("sha256") if isinstance(record, dict) else None
        if not isinstance(hashes, list) or not all(
            isinstance(value, str) and len(value) == 64 for value in hashes
        ):
            raise ValueError(f"DET-HASHES-{name}")
        predicates.append(stable(hashes, repetitions) and record.get("stable") is True)
    expected = "PASS" if all(predicates) else "FAIL"
    if report["verdict"] != expected:
        raise ValueError("DET-VERDICT-CONTRADICTION")


def main() -> int:
    repetitions = int(os.getenv("KORPUS_DETERMINISM_REPETITIONS", "3"))
    if repetitions < 2 or repetitions > 20:
        raise SystemExit("KORPUS_DETERMINISM_REPETITIONS must be in [2, 20]")
    environment = os.environ.copy()
    environment.update({"PYTHONHASHSEED": "0", "TZ": "UTC", "LC_ALL": "C.UTF-8"})
    hashes: dict[str, list[str]] = {"eval_report": [], "system_manifest": []}
    commands = (
        ([sys.executable, "scripts/run_evals.py"], ROOT / "var/eval-report.json", "eval_report"),
        (
            [
                sys.executable,
                "scripts/build_system_manifest.py",
                "--output",
                "var/system-manifest.json",
            ],
            ROOT / "var/system-manifest.json",
            "system_manifest",
        ),
    )
    for _ in range(repetitions):
        for command, artifact, name in commands:
            subprocess.run(command, cwd=ROOT, env=environment, check=True, capture_output=True)
            if not artifact.is_file():
                raise RuntimeError(f"DET-MISSING-ARTIFACT:{artifact.relative_to(ROOT)}")
            hashes[name].append(sha256(artifact))
    candidate = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    artifacts = {
        name: {"sha256": values, "stable": stable(values, repetitions)}
        for name, values in hashes.items()
    }
    report = {
        "schema": "korpus.determinism-assurance.v1",
        "candidate_commit": candidate,
        "repetitions": repetitions,
        "artifacts": artifacts,
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "pythonhashseed": "0", "timezone": "UTC", "locale": "C.UTF-8",
        },
        "production_authorized": False,
        "verdict": "PASS" if all(item["stable"] for item in artifacts.values()) else "FAIL",
    }
    validate_report(report)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
