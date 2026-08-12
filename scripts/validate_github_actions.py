#!/usr/bin/env python3
"""Fail-closed source policy for GitHub Actions workflows."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
ACTION_LINE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^#\s]+)", re.MULTILINE)
FORBIDDEN_TRIGGERS = ("pull_request_target", "workflow_run")


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("workflow root is not a mapping")
    return data


def _action_findings(name: str, text: str) -> list[str]:
    findings: list[str] = []
    for target in ACTION_LINE.findall(text):
        if target.startswith("./"):
            continue
        action, separator, ref = target.rpartition("@")
        if not separator or not FULL_SHA.fullmatch(ref):
            findings.append(f"{name}: action is not pinned to full SHA: {target}")
        elif not action:
            findings.append(f"{name}: action name is empty: {target}")
    return findings


def _job_findings(name: str, jobs: object) -> list[str]:
    if not isinstance(jobs, dict) or not jobs:
        return [f"{name}: no jobs"]
    findings: list[str] = []
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            findings.append(f"{name}:{job_name}: job is not a mapping")
            continue
        runner = job.get("runs-on")
        if not isinstance(runner, str) or runner.endswith("-latest"):
            findings.append(f"{name}:{job_name}: runner must be an explicit fixed label")
        timeout = job.get("timeout-minutes")
        if not isinstance(timeout, int) or timeout <= 0:
            findings.append(f"{name}:{job_name}: missing positive timeout-minutes")
        findings.extend(_checkout_findings(name, str(job_name), job.get("steps")))
    return findings


def _checkout_findings(name: str, job_name: str, steps: object) -> list[str]:
    if not isinstance(steps, list):
        return [f"{name}:{job_name}: steps is not a list"]
    findings: list[str] = []
    for step in steps:
        if not isinstance(step, dict) or not str(step.get("uses", "")).startswith("actions/checkout@"):
            continue
        inputs = step.get("with")
        persist = inputs.get("persist-credentials") if isinstance(inputs, dict) else None
        if persist is not False and str(persist).lower() != "false":
            findings.append(f"{name}:{job_name}: checkout must set persist-credentials: false")
    return findings


def validate_workflow(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    try:
        data = _load(path)
    except (OSError, yaml.YAMLError, ValueError) as error:
        return [f"{path.name}: invalid YAML: {error}"]
    findings = [] if "permissions" in data else [f"{path.name}: missing explicit top-level permissions"]
    findings.extend(
        f"{path.name}: forbidden privileged trigger {trigger}"
        for trigger in FORBIDDEN_TRIGGERS
        if re.search(rf"^\s*{re.escape(trigger)}\s*:", text, re.MULTILINE)
    )
    findings.extend(_action_findings(path.name, text))
    findings.extend(_job_findings(path.name, data.get("jobs")))
    return findings


def validate_repository(root: Path = ROOT) -> list[str]:
    workflow_dir = root / ".github/workflows"
    paths = sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml"))) if workflow_dir.is_dir() else []
    if not paths:
        return [".github/workflows: no workflow files"]
    findings = [finding for path in paths for finding in validate_workflow(path)]
    import_doc, release_path = root / "GITHUB_IMPORT.md", root / "apps/api/src/korpus/release.json"
    if not import_doc.is_file():
        findings.append("GITHUB_IMPORT.md: missing")
    elif release_path.is_file():
        release = json.loads(release_path.read_text(encoding="utf-8"))
        text = import_doc.read_text(encoding="utf-8")
        if str(release.get("tag", "")) not in text or f'{release.get("artifact_stem", "")}.bundle' not in text:
            findings.append("GITHUB_IMPORT.md: release identity is stale")
    return sorted(findings)


def main() -> int:
    findings = validate_repository()
    payload = {
        "schema": "korpus.github-actions-policy.v1",
        "valid": not findings,
        "workflow_count": len(list(WORKFLOWS.glob("*.y*ml"))) if WORKFLOWS.is_dir() else 0,
        "findings": findings,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
