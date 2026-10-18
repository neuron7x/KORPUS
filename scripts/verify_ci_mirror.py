#!/usr/bin/env python3
"""Verify that mandatory GitHub PR workflows mirror local ``validate``/``check``."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_mirror_evidence import evidence_problems
from ci_mirror_evidence import selftest as evidence_selftest
from verify_gate_closure import invocations, parse_graph, reachable

ROOT = Path(__file__).resolve().parents[1]
MIRRORED_ROOTS: tuple[str, ...] = ("validate", "check")
LOCAL_ONLY_ROOTS: tuple[str, ...] = ("check-deployment", "check-nightly")

_MAKE_CALL = re.compile(
    r"(?:^|[;&|]\s*|\s)make\s+(?:-C\s+\S+\s+)?([A-Za-z0-9._-]+(?:\s+[A-Za-z0-9._-]+)*)"
)
_MAKE_TARGET = re.compile(r"^[A-Za-z0-9._-]+$")
SELFTEST_COVERAGE = "scripts/verify_selftest_coverage.py"


def lane_invocations(makefile: str, roots: tuple[str, ...]) -> dict[str, set[str]]:
    edges, _declared, scripts = parse_graph(makefile)
    found: dict[str, set[str]] = {}
    for target in reachable(edges, roots):
        for identity in scripts.get(target, ()):
            found.setdefault(identity, set()).add(target)
    return found


def workflow_runs_on_pull_request(workflow: dict[Any, Any]) -> bool:
    triggers = workflow.get("on") if "on" in workflow else workflow.get(True)
    if isinstance(triggers, str):
        return triggers == "pull_request"
    if isinstance(triggers, list):
        return "pull_request" in triggers
    return isinstance(triggers, dict) and "pull_request" in triggers


def mandatory_workflow_jobs(workflow: dict[str, Any]) -> list[str]:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return []
    return sorted(
        str(body.get("name") or job_id)
        for job_id, body in jobs.items()
        if isinstance(body, dict)
        and body.get("if") is None
        and body.get("continue-on-error") in (None, False)
    )


def _is_gate(item: dict[str, Any], kind: str) -> tuple[bool, str]:
    if item.get("if") is not None:
        return False, f"conditional {kind} (if)"
    if item.get("continue-on-error") not in (None, False):
        return False, f"continue-on-error {kind}"
    return True, ""


def _line_identities(
    line: str, edges: dict[str, set[str]], scripts: dict[str, set[str]]
) -> set[str]:
    found = set(invocations(line))
    for call in _MAKE_CALL.finditer(line):
        targets = tuple(target for target in call.group(1).split() if _MAKE_TARGET.match(target))
        for target in reachable(edges, targets):
            found.update(scripts.get(target, ()))
    return found


def _job_invocations(
    job: dict[str, Any],
    job_key: str,
    edges: dict[str, set[str]],
    scripts: dict[str, set[str]],
) -> tuple[dict[str, set[str]], dict[str, str]]:
    found: dict[str, set[str]] = {}
    gate, why = _is_gate(job, "job")
    if not gate:
        return found, {job_key: why}
    steps = job.get("steps")
    if not isinstance(steps, list):
        return found, {job_key: "job has no inline steps"}
    excluded: dict[str, str] = {}
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("run"), str):
            continue
        step_key = f"{job_key}/{step.get('name') or index}"
        step_gate, step_why = _is_gate(step, "step")
        if not step_gate:
            excluded[step_key] = step_why
            continue
        for line in str(step["run"]).splitlines():
            for identity in _line_identities(line, edges, scripts):
                found.setdefault(identity, set()).add(job_key)
    return found, excluded


def workflow_invocations(
    workflow: dict[str, Any], makefile: str, *, source: str = "workflow"
) -> tuple[dict[str, set[str]], dict[str, str]]:
    edges, _declared, scripts = parse_graph(makefile)
    found: dict[str, set[str]] = {}
    excluded: dict[str, str] = {}
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return found, {source: "workflow has no jobs mapping"}
    for job_id, raw_job in jobs.items():
        if not isinstance(raw_job, dict):
            excluded[f"{source}:{job_id}"] = "job is not a mapping"
            continue
        job_name = str(raw_job.get("name") or job_id)
        job_key = f"{source}:{job_name}"
        job_ci, job_excluded = _job_invocations(raw_job, job_key, edges, scripts)
        for identity, owners in job_ci.items():
            found.setdefault(identity, set()).update(owners)
        excluded.update(job_excluded)
    return found, excluded


def _finding(check: str, items: list[str], bad: str, good: str) -> dict[str, Any]:
    return {
        "check": check,
        "verdict": "FAIL" if items else "PASS",
        "detail": bad if items else good,
        "items": items,
    }


def _reasoned(item: dict[str, Any]) -> bool:
    return len(str(item.get("reason") or "").strip()) >= 40 and bool(item.get("on"))


def assess(
    lane: dict[str, set[str]],
    ci: dict[str, set[str]],
    accepted: list[dict[str, Any]],
    errors: tuple[list[str], list[str]] | None = None,
) -> list[dict[str, Any]]:
    registered = {str(item.get("invocation")) for item in accepted}
    via_coverage = SELFTEST_COVERAGE in ci
    covered = {
        identity
        for identity in lane
        if via_coverage and identity.endswith(" --selftest") and identity.startswith("scripts/")
    }
    missing = sorted(
        identity
        for identity in lane
        if identity not in ci and identity not in registered and identity not in covered
    )
    dead = sorted(identity for identity in registered if identity in ci)
    ghost = sorted(identity for identity in registered if identity not in lane)
    unreasoned = sorted(str(item.get("invocation")) for item in accepted if not _reasoned(item))
    workflow_errors, evidence_errors = errors or ([], [])
    invalid_workflows = sorted(workflow_errors)
    unsupported = sorted(evidence_errors)
    return [
        _finding(
            "mandatory_pr_workflows",
            invalid_workflows,
            f"invalid workflows: {invalid_workflows}",
            "workflows valid",
        ),
        _finding("missing_in_ci", missing, f"GitHub misses {missing}", f"all {len(lane)} covered"),
        _finding("dead_exemption", dead, f"dead exemptions: {dead}", "none dead"),
        _finding("ghost_exemption", ghost, f"ghost exemptions: {ghost}", "none ghost"),
        _finding("reasoned_exemption", unreasoned, f"unreasoned: {unreasoned}", "all reasoned"),
        _finding("exemption_evidence", unsupported, f"unsupported: {unsupported}", "all proven"),
    ]


def verdict(findings: list[dict[str, Any]]) -> str:
    return "FAIL" if any(item["verdict"] != "PASS" for item in findings) else "PASS"


_CLEAN_MAKE = "validate: a-gate\n\na-gate:\n\t$(PY) scripts/a.py --strict\n\ncheck: validate\n"


def _workflow(run: str, **job_fields: Any) -> dict[str, Any]:
    job: dict[str, Any] = {
        "name": "gate",
        "runs-on": "ubuntu-24.04",
        "steps": [{"run": run}],
    }
    job.update(job_fields)
    return {"on": {"pull_request": None}, "jobs": {"gate": job}}


_CLEAN_CI = _workflow("PYTHONPATH=x python scripts/a.py --strict")
_PROOF_MAKE = (
    "validate: a-gate\n\na-gate:\n\t$(PY) scripts/a.py --selftest\n"
    "\t$(PY) scripts/a.py --strict\n\ncheck: validate\n"
)
_ACCEPTED = [
    {
        "invocation": "scripts/a.py --strict",
        "on": "x",
        "reason": "x" * 40,
    }
]


def _step_workflow(field: str) -> dict[str, Any]:
    workflow = _workflow("python scripts/a.py --strict")
    workflow["jobs"]["gate"]["steps"][0][field] = True
    return workflow


_CASES: list[tuple[str, str, dict[str, Any], list[dict[str, Any]], list[str], str]] = [
    ("clean mirror", _CLEAN_MAKE, _CLEAN_CI, [], [], "PASS"),
    ("missing", _CLEAN_MAKE, _workflow("echo"), [], [], "FAIL"),
    (
        "selftest differs",
        _CLEAN_MAKE,
        _workflow("python scripts/a.py --selftest"),
        [],
        [],
        "FAIL",
    ),
    ("flag differs", _CLEAN_MAKE, _workflow("python scripts/a.py"), [], [], "FAIL"),
    (
        "soft job",
        _CLEAN_MAKE,
        _workflow("python scripts/a.py --strict", **{"continue-on-error": True}),
        [],
        [],
        "FAIL",
    ),
    (
        "conditional job",
        _CLEAN_MAKE,
        _workflow("python scripts/a.py --strict", **{"if": "false"}),
        [],
        [],
        "FAIL",
    ),
    ("conditional step", _CLEAN_MAKE, _step_workflow("if"), [], [], "FAIL"),
    ("soft step", _CLEAN_MAKE, _step_workflow("continue-on-error"), [], [], "FAIL"),
    ("make expansion", _CLEAN_MAKE, _workflow("make validate"), [], [], "PASS"),
    ("accepted", _CLEAN_MAKE, _workflow("echo"), _ACCEPTED, [], "PASS"),
    ("dead exemption", _CLEAN_MAKE, _CLEAN_CI, _ACCEPTED, [], "FAIL"),
    (
        "ghost exemption",
        _CLEAN_MAKE,
        _CLEAN_CI,
        [{"invocation": "scripts/zzz.py", "on": "x", "reason": "x" * 40}],
        [],
        "FAIL",
    ),
    (
        "unreasoned exemption",
        _CLEAN_MAKE,
        _workflow("echo"),
        [{"invocation": "scripts/a.py --strict", "on": "x", "reason": "short"}],
        [],
        "FAIL",
    ),
    (
        "selftests covered",
        _PROOF_MAKE,
        _workflow("python scripts/a.py --strict\npython scripts/verify_selftest_coverage.py"),
        [],
        [],
        "PASS",
    ),
    (
        "selftest gap",
        _PROOF_MAKE,
        _workflow("python scripts/a.py --strict"),
        [],
        [],
        "FAIL",
    ),
    ("invalid workflow", _CLEAN_MAKE, _CLEAN_CI, [], ["ci.yml: no PR"], "FAIL"),
]


def selftest() -> int:
    bad = 0
    for name, makefile, workflow, accepted, errors, expected in _CASES:
        lane = lane_invocations(makefile, MIRRORED_ROOTS)
        ci, _excluded = workflow_invocations(workflow, makefile)
        got = verdict(assess(lane, ci, accepted, (errors, [])))
        ok = got == expected
        bad += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {name}: {got}")
    print(f"\nnegative controls: {len(_CASES) - bad}/{len(_CASES)}")
    return 1 if bad or evidence_selftest() else 0


def _head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    ).stdout.strip()


def _read_workflow(root: Path, relative: Path) -> tuple[dict[str, Any] | None, str]:
    label = relative.as_posix()
    if relative.is_absolute() or ".." in relative.parts:
        return None, f"{label}: path escapes repository"
    path = root / relative
    if not path.is_file():
        return None, f"{label}: missing"
    try:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return None, f"{label}: invalid YAML ({exc.__class__.__name__})"
    if not isinstance(workflow, dict):
        return None, f"{label}: root is not a mapping"
    if not workflow_runs_on_pull_request(workflow):
        return None, f"{label}: does not run on pull_request"
    if not isinstance(workflow.get("jobs"), dict) or not workflow["jobs"]:
        return None, f"{label}: no jobs"
    return workflow, ""


def _load_workflows(
    root: Path, paths: Any, makefile: str
) -> tuple[dict[str, set[str]], dict[str, str], list[str], list[str]]:
    found: dict[str, set[str]] = {}
    excluded: dict[str, str] = {}
    errors: list[str] = []
    loaded: list[str] = []
    if not isinstance(paths, list) or not paths:
        return found, excluded, ["mandatory_pr_workflows is empty"], loaded
    for raw_path in paths:
        relative = Path(str(raw_path))
        label = relative.as_posix()
        if label in loaded:
            errors.append(f"{label}: duplicated")
            continue
        workflow, error = _read_workflow(root, relative)
        if workflow is None:
            errors.append(error)
            continue
        loaded.append(label)
        workflow_ci, workflow_excluded = workflow_invocations(workflow, makefile, source=label)
        for identity, jobs in workflow_ci.items():
            found.setdefault(identity, set()).update(jobs)
        excluded.update(workflow_excluded)
    return found, excluded, errors, loaded


def measure(root: Path) -> dict[str, Any]:
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    registry = json.loads((root / "config/operations/ci-mirror.json").read_text(encoding="utf-8"))
    accepted = list(registry.get("accepted") or [])
    lane = lane_invocations(makefile, MIRRORED_ROOTS)
    ci, excluded, workflow_errors, workflows = _load_workflows(
        root, registry.get("mandatory_pr_workflows"), makefile
    )
    local_only = {name: len(lane_invocations(makefile, (name,))) for name in LOCAL_ONLY_ROOTS}
    findings = assess(lane, ci, accepted, (workflow_errors, evidence_problems(root, accepted)))
    mirrored = sorted(identity for identity in lane if identity in ci)
    return {
        "schema": "korpus.ci-mirror.v2",
        "provider": "github-actions",
        "commit": _head(root),
        "ran_at": datetime.now(UTC).isoformat(),
        "roots": list(MIRRORED_ROOTS),
        "mandatory_pr_workflows": workflows,
        "lane_invocations": len(lane),
        "mirrored": len(mirrored),
        "accepted": len(accepted),
        "jobs_outside_mirror": excluded,
        "local_only_lanes": local_only,
        "findings": findings,
        "status": verdict(findings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "var/ci-mirror.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    report = measure(arguments.root)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for item in report["findings"]:
        print(f"  [{item['verdict']}] {item['check']}: {item['detail']}")
    print(
        f"\nci-mirror: {report['status']} ({report['mirrored']}/{report['lane_invocations']} "
        f"lane commands in GitHub PR CI, {report['accepted']} accepted) -> {arguments.out}"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
