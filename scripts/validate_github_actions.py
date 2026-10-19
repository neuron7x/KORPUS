#!/usr/bin/env python3
"""Fail-closed source policy for GitHub Actions workflows."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import github_actions_graph as graph  # noqa: E402

WORKFLOWS = ROOT / ".github/workflows"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
ACTION_LINE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^#\s]+)", re.MULTILINE)
FORBIDDEN_TRIGGERS = ("pull_request_target", "workflow_run")


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


def _trigger_findings(name: str, text: str) -> list[str]:
    return [
        f"{name}: forbidden privileged trigger {trigger}"
        for trigger in FORBIDDEN_TRIGGERS
        if re.search(rf"^\s*{re.escape(trigger)}\s*:", text, re.MULTILINE)
    ]


def validate_workflow(path: Path, ancestors: tuple[Path, ...] = ()) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
        data = graph.load(path)
    except (OSError, yaml.YAMLError, ValueError) as error:
        return [f"{path.name}: invalid YAML: {error}"]
    findings = (
        [] if "permissions" in data else [f"{path.name}: missing explicit top-level permissions"]
    )
    findings.extend(_trigger_findings(path.name, text))
    findings.extend(_action_findings(path.name, text))
    findings.extend(graph.job_findings(path.name, data.get("jobs")))
    findings.extend(
        graph.reusable_findings(
            path, data.get("jobs"), (*ancestors, path.resolve()), validate_workflow
        )
    )
    return findings


def validate_repository(root: Path = ROOT) -> list[str]:
    workflow_dir = root / ".github/workflows"
    paths = (
        sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))
        if workflow_dir.is_dir()
        else []
    )
    if not paths:
        return [".github/workflows: no workflow files"]
    findings = [finding for path in paths for finding in validate_workflow(path)]
    import_doc, release_path = root / "GITHUB_IMPORT.md", root / "apps/api/src/korpus/release.json"
    if not import_doc.is_file():
        findings.append("GITHUB_IMPORT.md: missing")
    elif release_path.is_file():
        release = json.loads(release_path.read_text(encoding="utf-8"))
        text = import_doc.read_text(encoding="utf-8")
        artifact = str(release.get("distribution_artifact", ""))
        if not artifact or str(release.get("tag", "")) not in text or artifact not in text:
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
