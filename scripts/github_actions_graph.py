"""Validate job dependencies and same-commit reusable workflow calls."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

LOCAL_WORKFLOW = re.compile(r"^\./\.github/workflows/([A-Za-z0-9_-]+\.ya?ml)$")
CALL_JOB_KEYS = frozenset(
    {"name", "uses", "needs", "if", "permissions", "with", "secrets", "strategy", "concurrency"}
)
Validator = Callable[[Path, tuple[Path, ...]], list[str]]


def load(path: Path) -> dict[Any, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("workflow root is not a mapping")
    return data


def _call_keys(name: str, job: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if not LOCAL_WORKFLOW.fullmatch(str(job["uses"])):
        findings.append(f"{name}: workflow call must use a local workflow file")
    unexpected = sorted(set(job) - CALL_JOB_KEYS)
    if unexpected:
        findings.append(f"{name}: invalid workflow call keys: {unexpected}")
    return findings


def _runner_findings(name: str, job: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    runner = job.get("runs-on")
    if not isinstance(runner, str) or runner.endswith("-latest"):
        findings.append(f"{name}: runner must be an explicit fixed label")
    timeout = job.get("timeout-minutes")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        findings.append(f"{name}: missing positive timeout-minutes")
    return findings


def job_findings(name: str, jobs: object) -> list[str]:
    if not isinstance(jobs, dict) or not jobs:
        return [f"{name}: no jobs"]
    findings: list[str] = []
    for key, job in jobs.items():
        label = f"{name}:{key}"
        if not isinstance(job, dict):
            findings.append(f"{label}: job is not a mapping")
        elif "uses" in job:
            findings.extend(_call_keys(label, job))
        else:
            findings.extend(_runner_findings(label, job))
            findings.extend(_checkout_findings(label, job.get("steps")))
    return findings + dependency_findings(name, jobs)


def _dependency_edges(name: str, jobs: dict[str, Any]) -> tuple[dict[str, list[str]], list[str]]:
    edges: dict[str, list[str]] = {}
    findings: list[str] = []
    for key, job in jobs.items():
        needs = job.get("needs", []) if isinstance(job, dict) else []
        needs = [needs] if isinstance(needs, str) else needs
        if not isinstance(needs, list) or any(not isinstance(item, str) for item in needs):
            findings.append(f"{name}:{key}: needs must name jobs explicitly")
            continue
        edges[key] = needs
        findings.extend(
            f"{name}:{key}: unknown dependency: {item}" for item in needs if item not in jobs
        )
    return edges, findings


def dependency_findings(name: str, jobs: dict[str, Any]) -> list[str]:
    edges, findings = _dependency_edges(name, jobs)
    visited: set[str] = set()

    def visit(key: str, trail: tuple[str, ...]) -> None:
        if key in trail:
            findings.append(f"{name}: job dependency cycle: {' -> '.join((*trail, key))}")
        elif key not in visited:
            for dependency in edges.get(key, []):
                visit(dependency, (*trail, key))
            visited.add(key)

    for key in edges:
        visit(key, ())
    return findings


def _checkout_findings(name: str, steps: object) -> list[str]:
    if not isinstance(steps, list):
        return [f"{name}: steps is not a list"]
    findings: list[str] = []
    for step in steps:
        if not isinstance(step, dict) or not str(step.get("uses", "")).startswith(
            "actions/checkout@"
        ):
            continue
        inputs = step.get("with")
        persist = inputs.get("persist-credentials") if isinstance(inputs, dict) else None
        if persist is not False and str(persist).lower() != "false":
            findings.append(f"{name}: checkout must set persist-credentials: false")
    return findings


def _callee_problem(callee: Path, directory: Path, ancestors: tuple[Path, ...]) -> str | None:
    if callee.resolve().parent != directory.resolve():
        return "reusable workflow escapes the workflow directory"
    if callee.resolve() in ancestors:
        return f"reusable workflow cycle: {callee.name}"
    try:
        data = load(callee)
    except (OSError, yaml.YAMLError, ValueError) as error:
        return f"unavailable reusable workflow: {error}"
    triggers = data.get("on", data.get(True))
    if triggers != "workflow_call" and not (
        isinstance(triggers, (dict, list)) and "workflow_call" in triggers
    ):
        return f"{callee.name} must declare workflow_call"
    return None


def reusable_findings(
    path: Path, jobs: object, ancestors: tuple[Path, ...], validate: Validator
) -> list[str]:
    findings: list[str] = []
    if not isinstance(jobs, dict):
        return findings
    for key, job in jobs.items():
        target = str(job.get("uses", "")) if isinstance(job, dict) else ""
        match = LOCAL_WORKFLOW.fullmatch(target)
        if match is None:
            continue
        callee = path.parent / match.group(1)
        problem = _callee_problem(callee, path.parent, ancestors)
        if problem:
            findings.append(f"{path.name}:{key}: {problem}")
        else:
            findings.extend(validate(callee, ancestors))
    return findings
