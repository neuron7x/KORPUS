"""Fail-closed GitHub Actions workflow/run/attempt provenance evidence."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple, TypeGuard

import yaml
from verify_ci_mirror import mandatory_workflow_jobs


@dataclass(frozen=True)
class WorkflowContract:
    path: str
    jobs: tuple[str, ...]


@dataclass(frozen=True)
class RunIdentity:
    repository: str
    path: str
    event: str
    workflow_id: int
    commit: str
    run_id: int
    attempt: int


@dataclass(frozen=True)
class JobCatalogue:
    required: tuple[str, ...] = ()
    workflows: tuple[WorkflowContract, ...] = ()
    excused: frozenset[str] = frozenset()
    repository: str = ""
    event: str = ""

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


@dataclass(frozen=True)
class ExactRunEvidence:
    workflow_id: int
    latest_run_id: int
    run: dict[str, Any]
    jobs: list[dict[str, Any]]


class ScannerRunEvidence(NamedTuple):
    repository: str
    workflow_id: int
    latest_run_id: int
    metadata: dict[str, Any]
    jobs: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    accepted_commits: frozenset[str]


class ArtifactRequest(NamedTuple):
    repository: str
    artifact_id: int
    file_name: str


class DownloadRequest(NamedTuple):
    repository: str
    accepted_commits: frozenset[str]
    report: dict[str, Any]
    write: bool


SCANNER_PRODUCER_JOBS = frozenset(
    {
        "security-gitleaks",
        "security-pip-audit",
        "security-trivy-config",
        "security-summary",
        "container-scan",
    }
)


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
        str(ci.get("repository") or ""),
        str(ci.get("required_event") or ""),
    )


def catalogue_drift(jobs: JobCatalogue) -> tuple[list[str], list[str], list[str]]:
    mandatory = list(jobs.mandatory)
    required_names = list(jobs.required)
    expected = set(mandatory) - set(jobs.excused)
    required = set(required_names)
    duplicates = sorted(
        {
            name
            for name in (*mandatory, *required_names)
            if mandatory.count(name) + required_names.count(name) > 2
        }
    )
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
    return (
        items
        if isinstance(total, int) and not isinstance(total, bool) and total == len(items)
        else None
    )


def integer(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def path_matches(raw: Any, expected: str) -> bool:
    return str(raw or "") == expected


def repository_matches(run: dict[str, Any], expected: str) -> bool:
    repository = run.get("repository")
    head_repository = run.get("head_repository")
    return (
        isinstance(repository, dict)
        and repository.get("full_name") == expected
        and isinstance(head_repository, dict)
        and head_repository.get("full_name") == expected
    )


def _pull_request_matches(run: dict[str, Any], identity: RunIdentity) -> bool:
    pull_requests = run.get("pull_requests")
    api_url = f"https://api.github.com/repos/{identity.repository}"
    if not isinstance(pull_requests, list) or not pull_requests:
        return False
    for pull_request in pull_requests:
        if not isinstance(pull_request, dict):
            continue
        head, base = pull_request.get("head"), pull_request.get("base")
        if not isinstance(head, dict) or not isinstance(base, dict):
            continue
        head_repo, base_repo = head.get("repo"), base.get("repo")
        if (
            isinstance(head_repo, dict)
            and isinstance(base_repo, dict)
            and head_repo.get("url") == api_url
            and base_repo.get("url") == api_url
            and head.get("sha") == identity.commit
            and head.get("ref") == run.get("head_branch")
        ):
            return True
    return False


def run_provenance_problems(
    run: Any, identity: RunIdentity, *, recorded_attempt: Any = None
) -> tuple[str, ...]:
    if not isinstance(run, dict):
        return (identity.path,)
    valid = (
        run.get("id") == identity.run_id
        and run.get("run_attempt") == identity.attempt
        and (recorded_attempt is None or recorded_attempt == identity.attempt)
        and run.get("workflow_id") == identity.workflow_id
        and str(run.get("head_sha") or "").lower() == identity.commit
        and run.get("event") == identity.event == "pull_request"
        and isinstance(run.get("head_branch"), str)
        and bool(run["head_branch"])
        and path_matches(run.get("path"), identity.path)
        and repository_matches(run, identity.repository)
        and _pull_request_matches(run, identity)
    )
    return () if valid else (identity.path,)


def workflow_ids(payload: Any, contracts: tuple[WorkflowContract, ...]) -> dict[str, int] | None:
    raw_workflows = page(payload, "workflows")
    if raw_workflows is None:
        return None
    expected = {contract.path for contract in contracts}
    found: dict[str, int] = {}
    for raw in raw_workflows:
        if not isinstance(raw, dict) or raw.get("path") not in expected:
            continue
        path, workflow_id = str(raw["path"]), raw.get("id")
        if path in found or not integer(workflow_id) or raw.get("state") != "active":
            return None
        found[path] = workflow_id
    return found if set(found) == expected else None


def latest_run(
    runs: list[Any], contract: WorkflowContract, workflow_id: int, commit: str, jobs: JobCatalogue
) -> dict[str, Any] | None:
    eligible = [
        run
        for run in runs
        if isinstance(run, dict)
        and str(run.get("head_sha") or "").lower() == commit
        and run.get("event") == jobs.event
        and run.get("workflow_id") == workflow_id
        and path_matches(run.get("path"), contract.path)
        and repository_matches(run, jobs.repository)
        and integer(run.get("id"))
        and integer(run.get("run_number"))
    ]
    return max(eligible, key=lambda run: (run["run_number"], run["id"]), default=None)


def fetch_evidence(
    repository: str, commit: str, jobs: JobCatalogue, root: Path
) -> dict[str, Any] | None:
    if repository != jobs.repository or jobs.event != "pull_request":
        return None
    identities = workflow_ids(
        _gh_api(root, f"repos/{repository}/actions/workflows?per_page=100"), jobs.workflows
    )
    if identities is None:
        return None
    evidence: list[dict[str, Any]] = []
    for contract in jobs.workflows:
        workflow_id = identities[contract.path]
        payload = _gh_api(
            root,
            f"repos/{repository}/actions/workflows/{workflow_id}/runs"
            f"?head_sha={commit}&event={jobs.event}&per_page=100",
        )
        runs = page(payload, "workflow_runs")
        if runs is None:
            return None
        run = latest_run(runs, contract, workflow_id, commit, jobs)
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


def fetch_exact_run(root: Path, repository: str, path: str, run_id: int) -> ExactRunEvidence | None:
    latest_metadata = _gh_api(root, f"repos/{repository}/actions/runs/{run_id}")
    if not isinstance(latest_metadata, dict):
        return None
    attempt = latest_metadata.get("run_attempt")
    if not integer(attempt) or attempt < 1:
        return None
    run = _gh_api(root, f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}")
    if not isinstance(run, dict) or run.get("id") != run_id:
        return None
    contract = WorkflowContract(path, ())
    ids = workflow_ids(
        _gh_api(root, f"repos/{repository}/actions/workflows?per_page=100"), (contract,)
    )
    if ids is None:
        return None
    workflow_id = ids[path]
    commit = str(run.get("head_sha") or "").lower()
    runs = page(
        _gh_api(
            root,
            f"repos/{repository}/actions/workflows/{workflow_id}/runs"
            f"?head_sha={commit}&event=pull_request&per_page=100",
        ),
        "workflow_runs",
    )
    catalogue_ = JobCatalogue(repository=repository, event="pull_request")
    selected = latest_run(runs or [], contract, workflow_id, commit, catalogue_)
    payload = _gh_api(
        root,
        f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100",
    )
    jobs = page(payload, "jobs")
    if (
        runs is None
        or selected is None
        or not integer(selected.get("id"))
        or jobs is None
        or any(not isinstance(job, dict) for job in jobs)
    ):
        return None
    return ExactRunEvidence(workflow_id, int(selected["id"]), run, jobs)


def fetch_run_artifacts(root: Path, repository: str, run_id: int) -> list[dict[str, Any]] | None:
    artifacts = page(
        _gh_api(root, f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100"),
        "artifacts",
    )
    if artifacts is None or any(not isinstance(artifact, dict) for artifact in artifacts):
        return None
    return artifacts


def _attach_latest_attempt(record: dict[str, Any], repository: str, root: Path) -> bool:
    run = record["run"]
    run_id, attempt = run.get("id"), run.get("run_attempt")
    if not integer(run_id) or not integer(attempt) or attempt < 1:
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
    jobs: JobCatalogue,
) -> Inspection:
    workflow_id, run = record.get("workflow_id"), record.get("run")
    expected = set(contract.jobs) - set(jobs.excused)
    if not isinstance(workflow_id, int) or not isinstance(run, dict):
        missing = tuple(f"{contract.path}:{name}" for name in sorted(expected))
        return Inspection("FAIL", "mandatory workflow did not run", missing=missing)
    run_id, attempt = run.get("id"), run.get("run_attempt")
    if not integer(run_id) or not integer(attempt):
        return Inspection(
            "FAIL", "workflow/run/attempt provenance mismatch", provenance=(contract.path,)
        )
    identity = RunIdentity(
        jobs.repository, contract.path, jobs.event, workflow_id, commit, run_id, attempt
    )
    provenance = run_provenance_problems(
        run, identity, recorded_attempt=record.get("attempt_number")
    )
    if provenance:
        return Inspection("FAIL", "workflow/run/attempt provenance mismatch", provenance=provenance)
    raw_jobs = page(record.get("jobs"), "jobs")
    if raw_jobs is None:
        return Inspection("NOT_MEASURED", "attempt jobs API returned a partial response")
    completed, missing_jobs, failed, job_provenance = inspect_jobs(
        raw_jobs, expected, contract.path, commit, run_id, attempt
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


def inspect_jobs(
    raw_jobs: list[Any],
    expected: set[str],
    path: str,
    commit: str,
    run_id: int,
    attempt: int,
) -> tuple[list[str], list[str], list[str], list[str]]:
    observed: dict[str, dict[str, Any]] = {}
    provenance: list[str] = []
    for raw in raw_jobs:
        if not isinstance(raw, dict):
            provenance.append(f"{path}:invalid-job")
            continue
        name = str(raw.get("name") or "")
        if (
            raw.get("run_id") != run_id
            or raw.get("run_attempt") != attempt
            or str(raw.get("head_sha") or "").lower() != commit
        ):
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


def successful_run_problem(
    run: dict[str, Any],
    identity: RunIdentity,
    latest_run_id: int,
    raw_jobs: list[dict[str, Any]],
    expected: frozenset[str],
) -> str | None:
    if run_provenance_problems(run, identity, recorded_attempt=identity.attempt):
        return "run repository/workflow/event/ref/SHA/attempt provenance mismatch"
    if latest_run_id != identity.run_id:
        return f"run {identity.run_id} is not latest exact-SHA pull_request run {latest_run_id}"
    if (run.get("status"), run.get("conclusion")) != ("completed", "success"):
        return f"run is {run.get('status')}/{run.get('conclusion')}, not completed/success"
    completed, missing, failed, provenance = inspect_jobs(
        raw_jobs,
        set(expected),
        identity.path,
        identity.commit,
        identity.run_id,
        identity.attempt,
    )
    if missing or failed or provenance or set(completed) != expected:
        return "required producer jobs are missing, unsuccessful, duplicated, or foreign"
    return None


def job_receipts(raw_jobs: list[dict[str, Any]], expected: frozenset[str]) -> list[dict[str, Any]]:
    keys = ("id", "name", "run_id", "run_attempt", "head_sha", "status", "conclusion")
    return [{key: job.get(key) for key in keys} for job in raw_jobs if job.get("name") in expected]


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
        _inspect_workflow(contract, records[contract.path], commit, jobs)
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
