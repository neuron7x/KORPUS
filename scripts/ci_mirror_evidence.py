"""Executable stronger-than contracts for accepted local/CI lane differences."""

from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path
from typing import Any

import yaml

_WORKFLOW = ".github/workflows/assurance.yml"
_ITEM_KEYS = {"invocation", "on", "class", "reason", "closes_when", "superseded_by"}
_CLASS = "superseded_by_stronger_ci_form"
_JOB_KEYS = {"id", "name", "commands", "needs", "uploads", "downloads"}
_EDGE_KEYS = {"producer", "consumer", "artifact"}
_LOCK = "config/operations/pip-audit-toolchain.lock"
_LOCKED_INSTALL = f"python -m pip install --require-hashes --no-deps -r {_LOCK}"

_SECURITY_JOBS = [
    {
        "id": "source-secret-scan",
        "name": "security-gitleaks",
        "commands": [
            "detect --source . --no-banner --redact --exit-code 1",
            '--log-opts "$GITHUB_SHA"',
        ],
        "needs": [],
        "uploads": ["security-gitleaks"],
        "downloads": [],
    },
    {
        "id": "python-dependency-audit",
        "name": "security-pip-audit",
        "commands": [
            _LOCKED_INSTALL,
            "pip-audit --strict --disable-pip --no-deps -r apps/api/requirements.runtime.lock",
            "pip-audit --strict --disable-pip --no-deps -r apps/api/requirements.dev.lock",
        ],
        "needs": [],
        "uploads": ["security-pip-audit"],
        "downloads": [],
    },
    {
        "id": "infrastructure-scan",
        "name": "security-trivy-config",
        "commands": [
            "config --exit-code 1 --severity HIGH,CRITICAL --ignorefile .trivyignore.yaml ."
        ],
        "needs": [],
        "uploads": ["security-trivy"],
        "downloads": [],
    },
    {
        "id": "security-summary",
        "name": "security-summary",
        "commands": [
            "scripts/aggregate_ci_security_summary.py",
            '--commit "$GITHUB_SHA"',
        ],
        "needs": ["source-secret-scan", "python-dependency-audit", "infrastructure-scan"],
        "uploads": ["security-summary"],
        "downloads": ["security-gitleaks", "security-pip-audit", "security-trivy"],
    },
]
_SECURITY_EDGES = [
    {
        "producer": "source-secret-scan",
        "consumer": "security-summary",
        "artifact": "security-gitleaks",
    },
    {
        "producer": "python-dependency-audit",
        "consumer": "security-summary",
        "artifact": "security-pip-audit",
    },
    {
        "producer": "infrastructure-scan",
        "consumer": "security-summary",
        "artifact": "security-trivy",
    },
]
_AUDIT_JOBS = [
    {
        "id": "research-assurance",
        "name": "research-assurance",
        "commands": [
            "scripts/run_evals.py",
            "scripts/run_mutation_shards.sh",
            "scripts/run_plasticity_gate.py",
        ],
        "needs": [],
        "uploads": ["research-assurance-evidence"],
        "downloads": [],
    },
    {
        "id": "assurance-drills",
        "name": "assurance-drills",
        "commands": ["scripts/chaos_matrix.py"],
        "needs": [],
        "uploads": ["assurance-drill-evidence"],
        "downloads": [],
    },
    copy.deepcopy(_SECURITY_JOBS[-1]),
    {
        "id": "audit-closure",
        "name": "audit-closure",
        "commands": ["scripts/build_audit_closure.py"],
        "needs": ["research-assurance", "assurance-drills", "security-summary"],
        "uploads": ["audit-closure-evidence"],
        "downloads": [
            "research-assurance-evidence",
            "assurance-drill-evidence",
            "security-summary",
        ],
    },
]
_AUDIT_EDGES = [
    {
        "producer": "research-assurance",
        "consumer": "audit-closure",
        "artifact": "research-assurance-evidence",
    },
    {
        "producer": "assurance-drills",
        "consumer": "audit-closure",
        "artifact": "assurance-drill-evidence",
    },
    {"producer": "security-summary", "consumer": "audit-closure", "artifact": "security-summary"},
]
CONTRACTS: dict[str, dict[str, Any]] = {
    "scripts/security_scan.sh": {
        "workflow": _WORKFLOW,
        "jobs": _SECURITY_JOBS,
        "edges": _SECURITY_EDGES,
    },
    "scripts/verify_audit_closure_local.py": {
        "workflow": _WORKFLOW,
        "jobs": _AUDIT_JOBS,
        "edges": _AUDIT_EDGES,
    },
}


def _needs(job: dict[str, Any]) -> list[str] | None:
    value = job.get("needs")
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value] if isinstance(value, list) else None


def _blocking_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps")
    if not isinstance(steps, list):
        return []
    return [
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("if") is None
        and step.get("continue-on-error") in (None, False)
    ]


def _artifact_steps(job: dict[str, Any], action: str) -> list[dict[str, Any]]:
    steps = job.get("steps")
    allowed_if = {None, "always()"} if action == "actions/upload-artifact@" else {None}
    if not isinstance(steps, list):
        return []
    return [
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("continue-on-error") in (None, False)
        and step.get("if") in allowed_if
    ]


def _artifacts(job: dict[str, Any], action: str) -> list[str]:
    names: list[str] = []
    immutable = re.compile(rf"^{re.escape(action)}[0-9a-f]{{40}}$")
    for step in _artifact_steps(job, action):
        uses, inputs = step.get("uses"), step.get("with")
        if isinstance(uses, str) and immutable.fullmatch(uses) and isinstance(inputs, dict):
            name = inputs.get("name")
            if isinstance(name, str):
                names.append(name)
    return sorted(names)


def _job_problems(job_id: str, expected: dict[str, Any], actual: Any) -> list[str]:
    if not isinstance(actual, dict):
        return [f"{job_id}: missing job"]
    problems: list[str] = []
    if actual.get("name") != expected["name"]:
        problems.append(f"{job_id}: wrong name")
    if actual.get("if") is not None or actual.get("continue-on-error") not in (None, False):
        problems.append(f"{job_id}: not unconditional blocking")
    if _needs(actual) != expected["needs"]:
        problems.append(f"{job_id}: wrong needs")
    steps = _blocking_steps(actual)
    run = "\n".join(str(step.get("run") or "") for step in steps)
    for command in expected["commands"]:
        if command not in run:
            problems.append(f"{job_id}: missing command {command}")
    installs = [line.strip() for line in run.splitlines() if "pip install" in line]
    if job_id == "python-dependency-audit" and installs != [_LOCKED_INSTALL]:
        problems.append(f"{job_id}: scanner install is not uniquely hash-locked")
    if _artifacts(actual, "actions/upload-artifact@") != sorted(expected["uploads"]):
        problems.append(f"{job_id}: wrong uploads")
    if _artifacts(actual, "actions/download-artifact@") != sorted(expected["downloads"]):
        problems.append(f"{job_id}: wrong downloads")
    return problems


def _edge_problems(spec: dict[str, Any], jobs: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for edge in spec["edges"]:
        producer = jobs.get(edge["producer"])
        consumer = jobs.get(edge["consumer"])
        if not isinstance(producer, dict) or not isinstance(consumer, dict):
            problems.append(f"edge {edge}: missing endpoint")
            continue
        uploads = _artifacts(producer, "actions/upload-artifact@")
        downloads = _artifacts(consumer, "actions/download-artifact@")
        if edge["artifact"] not in uploads or edge["artifact"] not in downloads:
            problems.append(f"edge {edge}: artifact is not producer-to-consumer")
        if edge["producer"] not in (_needs(consumer) or []):
            problems.append(f"edge {edge}: producer absent from consumer needs")
    return problems


def _closed_spec(invocation: str, item: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    expected = CONTRACTS[invocation]
    if set(item) != _ITEM_KEYS:
        problems.append(f"{invocation}: accepted keys are not closed")
    if item.get("class") != _CLASS:
        problems.append(f"{invocation}: unknown class")
    if len(str(item.get("reason") or "").strip()) < 40 or not item.get("on"):
        problems.append(f"{invocation}: missing reason/date")
    if item.get("superseded_by") != expected:
        problems.append(f"{invocation}: superseded_by differs from executable contract")
    return problems


def assess(accepted: Any, workflows: dict[str, Any]) -> list[str]:
    if not isinstance(accepted, list):
        return ["accepted is not a list"]
    items = [item for item in accepted if isinstance(item, dict)]
    invocations = [str(item.get("invocation") or "") for item in items]
    problems = [] if len(items) == len(accepted) else ["accepted item is not a mapping"]
    if sorted(invocations) != sorted(CONTRACTS):
        problems.append("accepted invocation set is not the closed known set")
    for item, invocation in zip(items, invocations, strict=True):
        if invocation not in CONTRACTS:
            continue
        spec = CONTRACTS[invocation]
        problems.extend(_closed_spec(invocation, item))
        workflow = workflows.get(spec["workflow"])
        jobs = workflow.get("jobs") if isinstance(workflow, dict) else None
        if not isinstance(jobs, dict):
            problems.append(f"{invocation}: workflow jobs missing")
            continue
        for expected in spec["jobs"]:
            if set(expected) != _JOB_KEYS:
                problems.append(f"{invocation}: internal job contract malformed")
                continue
            problems.extend(_job_problems(expected["id"], expected, jobs.get(expected["id"])))
        if any(set(edge) != _EDGE_KEYS for edge in spec["edges"]):
            problems.append(f"{invocation}: internal edge contract malformed")
        problems.extend(_edge_problems(spec, jobs))
    return sorted(set(problems))


def evidence_problems(root: Path, accepted: Any) -> list[str]:
    workflows: dict[str, Any] = {}
    for spec in CONTRACTS.values():
        path = str(spec["workflow"])
        try:
            payload = yaml.safe_load((root / path).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            payload = {}
        workflows[path] = payload
    try:
        lock_text = (root / _LOCK).read_text(encoding="utf-8")
    except OSError:
        lock_text = ""
    return sorted(set([*assess(accepted, workflows), *_lock_problems(lock_text)]))


def _lock_problems(text: str) -> list[str]:
    logical = re.sub(r"\\\n\s*", " ", text)
    records = [
        line.strip()
        for line in logical.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    problems: list[str] = []
    for record in records:
        requirement = record.split(maxsplit=1)[0]
        hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})(?:\s|$)", record)
        hash_tokens = re.findall(r"--hash=([^\s]+)", record)
        pinned = re.fullmatch(r"[A-Za-z0-9_.-]+(?:\[[^]]+\])?==[A-Za-z0-9_.+!-]+", requirement)
        if pinned is None or not hashes or len(hashes) != len(hash_tokens):
            problems.append(f"unhashed toolchain record: {requirement}")
    if not any(record.startswith("pip-audit==2.10.1 ") for record in records):
        problems.append("pip-audit==2.10.1 absent from toolchain lock")
    return problems


def _synthetic() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    jobs: dict[str, Any] = {}
    for spec in CONTRACTS.values():
        for expected in spec["jobs"]:
            jobs[expected["id"]] = {
                "name": expected["name"],
                "needs": expected["needs"],
                "steps": [
                    {"run": "\n".join(expected["commands"])},
                    *[
                        {
                            "uses": f"actions/upload-artifact@{'a' * 40}",
                            "with": {"name": name},
                        }
                        for name in expected["uploads"]
                    ],
                    *[
                        {
                            "uses": f"actions/download-artifact@{'b' * 40}",
                            "with": {"name": name},
                        }
                        for name in expected["downloads"]
                    ],
                ],
            }
    accepted = [
        {
            "invocation": invocation,
            "on": "2026-10-19",
            "class": _CLASS,
            "reason": "x" * 40,
            "closes_when": "executable equivalence becomes direct",
            "superseded_by": copy.deepcopy(spec),
        }
        for invocation, spec in CONTRACTS.items()
    ]
    return accepted, {_WORKFLOW: {"on": {"pull_request": None}, "jobs": jobs}}


def selftest() -> int:
    accepted, workflows = _synthetic()

    def poisoned(*path: str | int, value: Any) -> list[str]:
        changed = copy.deepcopy(workflows)
        target: Any = changed[_WORKFLOW]["jobs"]
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return assess(accepted, changed)

    cases = [
        ("clean", assess(accepted, workflows), False),
        (
            "plausible job name without scanner",
            poisoned("source-secret-scan", "steps", value=[{"run": "echo gitleaks"}]),
            True,
        ),
        ("missing scanner", poisoned("source-secret-scan", value=None), True),
        (
            "missing upload",
            poisoned(
                "source-secret-scan",
                "steps",
                value=[{"run": "\n".join(_SECURITY_JOBS[0]["commands"])}],
            ),
            True,
        ),
        (
            "missing download",
            poisoned(
                "security-summary",
                "steps",
                value=[{"run": "\n".join(_SECURITY_JOBS[-1]["commands"])}],
            ),
            True,
        ),
        (
            "wrong artifact",
            poisoned("source-secret-scan", "steps", 1, "with", "name", value="lookalike"),
            True,
        ),
        ("wrong needs", poisoned("security-summary", "needs", value=[]), True),
        (
            "mutable scanner install",
            poisoned(
                "python-dependency-audit",
                "steps",
                value=[
                    {
                        "run": "\n".join(
                            [
                                _LOCKED_INSTALL,
                                "python -m pip install pip-audit==2.10.1",
                                *_SECURITY_JOBS[1]["commands"][1:],
                            ]
                        )
                    },
                    {
                        "uses": f"actions/upload-artifact@{'a' * 40}",
                        "with": {"name": "security-pip-audit"},
                    },
                ],
            ),
            True,
        ),
        ("unhashed toolchain lock", _lock_problems("pip-audit==2.10.1"), True),
        (
            "non-sha256 toolchain lock",
            _lock_problems(f"pip-audit==2.10.1 --hash=sha256:{'a' * 64} --hash=md5:bad"),
            True,
        ),
    ]
    passed = sum(bool(problems) is expected for _name, problems, expected in cases)
    for name, problems, expected in cases:
        ok = bool(problems) is expected
        print(f"  {'ok' if ok else 'FAIL'} evidence {name}: {len(problems)} problem(s)")
    print(f"exemption evidence controls: {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", required=True)
    parser.parse_args()
    return selftest()


if __name__ == "__main__":
    sys.exit(main())
