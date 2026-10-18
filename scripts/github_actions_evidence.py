"""Fail-closed GitHub Actions workflow/run/attempt provenance evidence."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml
from verify_ci_mirror import mandatory_workflow_jobs


@dataclass(frozen=True)
class WorkflowContract:
    path: str
    jobs: tuple[str, ...]


@dataclass(frozen=True)
class JobCatalogue:
    required: tuple[str, ...] = ()
    workflows: tuple[WorkflowContract, ...] = ()
    excused: frozenset[str] = frozenset()

    @property
    def mandatory(self) -> tuple[str, ...]:
        return tuple(name for workflow in self.workflows for name in workflow.jobs)


@dataclass(frozen=True)
class Inspection:
    status: str
    detail: str
    completed: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    runs: dict[str, dict[str, Any]] | None = None


def catalogue(ci: dict[str, Any], root: Path) -> JobCatalogue:
    workflows: list[WorkflowContract] = []
    for raw in ci.get("mandatory_pr_workflows") or ():
        relative = Path(str(raw))
        names: list[str] = []
        if not relative.is_absolute() and ".." not in relative.parts:
            try:
                workflow = yaml.safe_load((root / relative).read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                workflow = {}
            if isinstance(workflow, dict):
                names = mandatory_workflow_jobs(workflow)
        workflows.append(WorkflowContract(relative.as_posix(), tuple(names)))
    return JobCatalogue(
        tuple(str(name) for name in ci.get("required_jobs") or ()),
        tuple(sorted(workflows, key=lambda item: item.path)),
        frozenset(str(name) for name in ci.get("jobs_not_required") or ()),
    )


def catalogue_drift(jobs: JobCatalogue) -> tuple[list[str], list[str], list[str]]:
    mandatory = list(jobs.mandatory)
    expected = set(mandatory) - set(jobs.excused)
    required = set(jobs.required)
    duplicates = sorted({name for name in mandatory if mandatory.count(name) > 1})
    return sorted(required - expected), sorted(expected - required), duplicates


def _gh_api(root: Path, endpoint: str) -> Any | None:
    result = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "GET",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
            endpoint,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def page(payload: Any, key: str) -> list[Any] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        return None
    items = payload[key]
    total = payload.get("total_count")
    return items if isinstance(total, int) and total == len(items) else None


def path_matches(raw: Any, expected: str) -> bool:
    value = str(raw or "")
    return value == expected or value.startswith(f"{expected}@")


def latest_run(runs: list[Any], path: str, workflow_id: int, commit: str) -> dict[str, Any] | None:
    eligible = [
        run
        for run in runs
        if isinstance(run, dict)
        and str(run.get("head_sha") or "").lower() == commit
        and run.get("workflow_id") == workflow_id
        and path_matches(run.get("path"), path)
        and isinstance(run.get("id"), int)
        and isinstance(run.get("run_number"), int)
    ]
    return max(eligible, key=lambda run: (run["run_number"], run["id"]), default=None)


def fetch_evidence(
    repository: str, commit: str, jobs: JobCatalogue, root: Path
) -> dict[str, Any] | None:
    evidence: list[dict[str, Any]] = []
    for contract in jobs.workflows:
        filename = quote(Path(contract.path).name, safe="")
        workflow = _gh_api(root, f"repos/{repository}/actions/workflows/{filename}")
        if not isinstance(workflow, dict):
            return None
        workflow_id = workflow.get("id")
        if not isinstance(workflow_id, int) or not path_matches(
            workflow.get("path"), contract.path
        ):
            return None
        payload = _gh_api(
            root,
            f"repos/{repository}/actions/workflows/{workflow_id}/runs"
            f"?head_sha={commit}&per_page=100",
        )
        runs = page(payload, "workflow_runs")
        if runs is None:
            return None
        run = latest_run(runs, contract.path, workflow_id, commit)
        record: dict[str, Any] = {
            "path": contract.path,
            "workflow_id": workflow_id,
            "run": run,
            "attempt_number": None,
            "jobs": None,
        }
        if run is not None and not _attach_latest_attempt(record, repository, root):
            return None
        evidence.append(record)
    return {"workflow_evidence": evidence}


def _attach_latest_attempt(record: dict[str, Any], repository: str, root: Path) -> bool:
    run = record["run"]
    run_id, attempt = run.get("id"), run.get("run_attempt")
    if not isinstance(run_id, int) or not isinstance(attempt, int) or attempt < 1:
        return False
    payload = _gh_api(
        root,
        f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100",
    )
    if page(payload, "jobs") is None:
        return False
    record.update(attempt_number=attempt, jobs=payload)
    return True


def _records(payload: Any) -> dict[str, dict[str, Any]] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_evidence"), list):
        return None
    records: dict[str, dict[str, Any]] = {}
    for raw in payload["workflow_evidence"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            return None
        path = raw["path"]
        if path in records:
            return None
        records[path] = raw
    return records


def _inspect_workflow(
    contract: WorkflowContract,
    record: dict[str, Any],
    commit: str,
    excused: frozenset[str],
) -> Inspection:
    workflow_id, run = record.get("workflow_id"), record.get("run")
    expected = set(contract.jobs) - set(excused)
    if not isinstance(workflow_id, int) or not isinstance(run, dict):
        missing = tuple(f"{contract.path}:{name}" for name in sorted(expected))
        return Inspection("FAIL", "mandatory workflow did not run", missing=missing)
    run_id, attempt = run.get("id"), run.get("run_attempt")
    if not isinstance(run_id, int) or not isinstance(attempt, int):
        return Inspection(
            "FAIL", "workflow/run/attempt provenance mismatch", provenance=(contract.path,)
        )
    provenance = _run_provenance_failures(
        contract.path, commit, workflow_id, run_id, attempt, record, run
    )
    if provenance:
        return Inspection("FAIL", "workflow/run/attempt provenance mismatch", provenance=provenance)
    raw_jobs = page(record.get("jobs"), "jobs")
    if raw_jobs is None:
        return Inspection("NOT_MEASURED", "attempt jobs API returned a partial response")
    completed, missing_jobs, failed, job_provenance = _inspect_jobs(
        raw_jobs, expected, contract.path, commit, run_id
    )
    if (run.get("status"), run.get("conclusion")) != ("completed", "success"):
        failed.append(f"{contract.path}:workflow-run")
    receipt = {
        contract.path: {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "attempt": attempt,
            "url": str(run.get("html_url") or ""),
        }
    }
    return Inspection(
        "FAIL" if missing_jobs or failed or job_provenance else "PASS",
        "workflow inspected",
        tuple(completed),
        tuple(missing_jobs),
        tuple(failed),
        tuple(job_provenance),
        receipt,
    )


def _run_provenance_failures(
    path: str,
    commit: str,
    workflow_id: int,
    run_id: Any,
    attempt: Any,
    record: dict[str, Any],
    run: dict[str, Any],
) -> tuple[str, ...]:
    valid = (
        isinstance(run_id, int)
        and isinstance(attempt, int)
        and record.get("attempt_number") == attempt
        and run.get("workflow_id") == workflow_id
        and str(run.get("head_sha") or "").lower() == commit
        and path_matches(run.get("path"), path)
    )
    return () if valid else (path,)


def _inspect_jobs(
    raw_jobs: list[Any], expected: set[str], path: str, commit: str, run_id: int
) -> tuple[list[str], list[str], list[str], list[str]]:
    observed: dict[str, dict[str, Any]] = {}
    provenance: list[str] = []
    for raw in raw_jobs:
        if not isinstance(raw, dict):
            provenance.append(f"{path}:invalid-job")
            continue
        name = str(raw.get("name") or "")
        if raw.get("run_id") != run_id or str(raw.get("head_sha") or "").lower() != commit:
            provenance.append(f"{path}:{name or 'unnamed'}")
        elif name in expected:
            if name in observed:
                provenance.append(f"{path}:{name}:duplicate")
            observed[name] = raw
    completed, failed = [], []
    for name, item in observed.items():
        identity = f"{path}:{name}"
        if (item.get("status"), item.get("conclusion")) == ("completed", "success"):
            completed.append(name)
        else:
            failed.append(identity)
    missing = [f"{path}:{name}" for name in sorted(expected - set(observed))]
    return completed, missing, failed, provenance


def inspect(commit: str, jobs: JobCatalogue, payload: Any) -> Inspection:
    records = _records(payload)
    if records is None:
        return Inspection("NOT_MEASURED", "Actions runs/jobs API returned an invalid response")
    expected_paths = {workflow.path for workflow in jobs.workflows}
    if set(records) != expected_paths:
        return Inspection("FAIL", "evidence belongs to different workflow files")
    if not any(isinstance(record.get("run"), dict) for record in records.values()):
        return Inspection("NOT_MEASURED", "no mandatory workflow runs exist for exact SHA")
    observations = [
        _inspect_workflow(contract, records[contract.path], commit, jobs.excused)
        for contract in jobs.workflows
    ]
    return _combine(observations)


def _combine(observations: list[Inspection]) -> Inspection:
    unavailable = next((item for item in observations if item.status == "NOT_MEASURED"), None)
    if unavailable:
        return unavailable
    completed: set[str] = set()
    missing: set[str] = set()
    failed: set[str] = set()
    provenance: set[str] = set()
    runs: dict[str, dict[str, Any]] = {}
    for item in observations:
        completed.update(item.completed)
        missing.update(item.missing)
        failed.update(item.failed)
        provenance.update(item.provenance)
        runs.update(item.runs or {})
    result = (tuple(sorted(completed)), tuple(sorted(missing)), tuple(sorted(failed)))
    if provenance:
        return Inspection(
            "FAIL",
            "workflow/run/attempt/job provenance mismatch",
            *result,
            tuple(sorted(provenance)),
            runs,
        )
    if missing:
        return Inspection("FAIL", f"required jobs missing: {sorted(missing)}", *result, runs=runs)
    if failed:
        return Inspection(
            "FAIL",
            f"required jobs/runs unsuccessful: {sorted(failed)}",
            *result,
            runs=runs,
        )
    return Inspection(
        "PASS", "exact workflow runs and latest attempts succeeded", result[0], runs=runs
    )
