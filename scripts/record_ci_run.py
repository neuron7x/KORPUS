#!/usr/bin/env python3
"""Record exact-attempt GitHub Actions jobs for one candidate commit SHA."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from github_actions_evidence import (  # noqa: E402
    JobCatalogue,
    WorkflowContract,
    catalogue,
    catalogue_drift,
    fetch_evidence,
    inspect,
    latest_run,
)


def candidate_ci() -> dict[str, Any]:
    payload = json.loads((ROOT / "RELEASE_ENVELOPE.json").read_text(encoding="utf-8"))
    candidate = payload.get("release_candidate")
    ci = candidate.get("ci") if isinstance(candidate, dict) else None
    return ci if isinstance(ci, dict) else {}


def head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip().lower()


def _base_report(commit: str, required: tuple[str, ...], url: str) -> dict[str, Any]:
    return {
        "schema": "korpus.ci-run.v3",
        "provider": "github-actions",
        "commit": commit,
        "required_jobs": sorted(required),
        "completed_jobs": [],
        "failed_jobs": [],
        "pipeline": url,
        "ran_at": datetime.now(UTC).isoformat(),
    }


def _stop(report: dict[str, Any], status: str, detail: str) -> dict[str, Any]:
    report.update(status=status, detail=detail)
    return report


def adjudicate(
    commit: str, jobs: JobCatalogue, payload: Any, *, checks_url: str = ""
) -> dict[str, Any]:
    report = _base_report(commit, jobs.required, checks_url)
    report.update(repository=jobs.repository, required_event=jobs.event)
    if not _FULL_SHA.fullmatch(commit):
        return _stop(report, "NOT_MEASURED", "кандидат не є повним commit SHA")
    if not jobs.required or not jobs.workflows or not jobs.repository or not jobs.event:
        return _stop(report, "NOT_MEASURED", "конверт не називає repository/event/workflows/jobs")
    if jobs.event != "pull_request":
        return _stop(report, "FAIL", "canonical CI authority вимагає pull_request event")
    undeclared, unrequired, duplicates = catalogue_drift(jobs)
    report.update(
        required_not_in_workflows=undeclared,
        workflow_jobs_not_required=unrequired,
        duplicate_workflow_jobs=duplicates,
    )
    if undeclared or unrequired or duplicates:
        return _stop(report, "FAIL", "required jobs не збігаються з exact workflow jobs")
    result = inspect(commit, jobs, payload)
    report.update(
        workflow_runs=result.runs or {},
        completed_jobs=list(result.completed),
        failed_jobs=list(result.failed),
        missing_jobs=list(result.missing),
        provenance_failures=list(result.provenance),
    )
    return _stop(report, result.status, result.detail)


_SELF_COMMIT = "c" * 40
_SELF_REPOSITORY = "neuron7x/KORPUS"
_SELF_BRANCH = "work/issue-54"


def _self_run(path: str, workflow_id: int, run_id: int, **changes: Any) -> dict[str, Any]:
    api = f"https://api.github.com/repos/{_SELF_REPOSITORY}"
    value = {
        "id": run_id,
        "run_number": run_id,
        "run_attempt": 1,
        "workflow_id": workflow_id,
        "path": path,
        "head_sha": _SELF_COMMIT,
        "head_branch": _SELF_BRANCH,
        "event": "pull_request",
        "repository": {"full_name": _SELF_REPOSITORY},
        "head_repository": {"full_name": _SELF_REPOSITORY},
        "pull_requests": [
            {
                "head": {
                    "sha": _SELF_COMMIT,
                    "ref": _SELF_BRANCH,
                    "repo": {"url": api},
                },
                "base": {"ref": "main", "repo": {"url": api}},
            }
        ],
        "status": "completed",
        "conclusion": "success",
        "html_url": f"https://example.invalid/runs/{run_id}",
    }
    value.update(changes)
    return value


def _self_job(name: str, run_id: int, **changes: Any) -> dict[str, Any]:
    value = {
        "id": run_id * 10,
        "name": name,
        "run_id": run_id,
        "run_attempt": 1,
        "head_sha": _SELF_COMMIT,
        "status": "completed",
        "conclusion": "success",
    }
    value.update(changes)
    return value


def _self_record(
    path: str, workflow_id: int, run_id: int, names: tuple[str, ...]
) -> dict[str, Any]:
    return {
        "path": path,
        "workflow_id": workflow_id,
        "run": _self_run(path, workflow_id, run_id),
        "attempt_number": 1,
        "jobs": {
            "total_count": len(names),
            "jobs": [_self_job(name, run_id) for name in names],
        },
    }


def selftest() -> int:
    commit = _SELF_COMMIT
    ci_path = ".github/workflows/ci.yml"
    assurance_path = ".github/workflows/assurance.yml"
    jobs = JobCatalogue(
        ("a", "b"),
        (WorkflowContract(ci_path, ("a",)), WorkflowContract(assurance_path, ("b",))),
        repository=_SELF_REPOSITORY,
        event="pull_request",
    )
    good = [
        _self_record(ci_path, 11, 101, ("a",)),
        _self_record(assurance_path, 12, 102, ("b",)),
    ]

    def changed(index: int, *keys: str | int, value: Any) -> list[dict[str, Any]]:
        altered: list[dict[str, Any]] = json.loads(json.dumps(good))
        target: Any = altered[index]
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
        return altered

    def judge(records: Any, catalogue_: JobCatalogue = jobs, sha: str = commit) -> str:
        payload = None if records is None else {"workflow_evidence": records}
        return str(adjudicate(sha, catalogue_, payload)["status"])

    missing = [good[0], _self_record(assurance_path, 12, 102, ())]
    no_run = changed(1, "run", value=None)
    no_run[1].update(attempt_number=None, jobs=None)
    no_runs = json.loads(json.dumps(no_run))
    no_runs[0].update(run=None, attempt_number=None, jobs=None)
    wrong_job_run = changed(1, "jobs", "jobs", value=[_self_job("b", 999)])
    duplicate_job = changed(0, "jobs", "jobs", value=[_self_job("a", 101), _self_job("a", 101)])
    duplicate_job[0]["jobs"]["total_count"] = 2
    partial = changed(0, "jobs", "total_count", value=2)
    selected = latest_run(
        [
            _self_run(ci_path, 11, 101),
            _self_run(ci_path, 11, 102, event="push"),
            _self_run(ci_path, 11, 103, event="workflow_dispatch"),
        ],
        jobs.workflows[0],
        11,
        commit,
        jobs,
    )
    cases: list[tuple[str, Any, Any]] = [
        ("API failure", judge(None), "NOT_MEASURED"),
        ("partial jobs response", judge(partial), "NOT_MEASURED"),
        ("zero workflow runs", judge(no_runs), "NOT_MEASURED"),
        ("ref is not exact SHA", judge([], sha="main"), "NOT_MEASURED"),
        ("empty denominator", judge(good, JobCatalogue()), "NOT_MEASURED"),
        (
            "duplicate required name",
            judge(
                good,
                JobCatalogue(
                    ("a", "a", "b"),
                    jobs.workflows,
                    repository=_SELF_REPOSITORY,
                    event="pull_request",
                ),
            ),
            "FAIL",
        ),
        ("all exact workflow jobs success", judge(good), "PASS"),
        ("missing required job", judge(missing), "FAIL"),
        (
            "skipped job",
            judge(changed(1, "jobs", "jobs", 0, "conclusion", value="skipped")),
            "FAIL",
        ),
        ("wrong job run", judge(wrong_job_run), "FAIL"),
        ("wrong job SHA", judge(changed(1, "jobs", "jobs", 0, "head_sha", value="d" * 40)), "FAIL"),
        ("wrong job attempt", judge(changed(1, "jobs", "jobs", 0, "run_attempt", value=2)), "FAIL"),
        (
            "wrong workflow same job",
            judge(changed(0, "run", "path", value=".github/workflows/other.yml@main")),
            "FAIL",
        ),
        (
            "workflow path ref suffix",
            judge(changed(0, "run", "path", value=f"{ci_path}@main")),
            "FAIL",
        ),
        ("wrong workflow id", judge(changed(0, "run", "workflow_id", value=999)), "FAIL"),
        ("wrong run SHA", judge(changed(0, "run", "head_sha", value="d" * 40)), "FAIL"),
        ("wrong event", judge(changed(0, "run", "event", value="push")), "FAIL"),
        ("missing PR provenance", judge(changed(0, "run", "pull_requests", value=[])), "FAIL"),
        ("wrong PR ref", judge(changed(0, "run", "head_branch", value="foreign")), "FAIL"),
        ("wrong base repo", judge(changed(0, "run", "repository", value=None)), "FAIL"),
        ("wrong head repo", judge(changed(0, "run", "head_repository", value=None)), "FAIL"),
        ("stale attempt", judge(changed(0, "run", "run_attempt", value=2)), "FAIL"),
        ("duplicate job names", judge(duplicate_job), "FAIL"),
        ("one workflow absent", judge(no_run), "FAIL"),
        ("failed workflow", judge(changed(0, "run", "conclusion", value="failure")), "FAIL"),
        (
            "newer non-PR run cannot replace PR",
            selected["id"] if selected else None,
            101,
        ),
    ]
    passed = sum(got == want for _name, got, want in cases)
    for name, got, want in cases:
        print(f"  {'ok' if got == want else 'FAIL'} {name}: {got!r}")
    print(f"negative controls: {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="")
    parser.add_argument("--out", type=Path, default=ROOT / "var/ci-run.json")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--evidence-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    ci = candidate_ci()
    commit = (arguments.commit or head()).lower()
    jobs = catalogue(ci, ROOT)
    repository = str(ci.get("repository") or "")
    payload = (
        fetch_evidence(repository, commit, jobs, ROOT)
        if repository and _FULL_SHA.fullmatch(commit)
        else None
    )
    url = f"https://github.com/{repository}/actions?query=head_sha%3A{commit}" if repository else ""
    report = adjudicate(commit, jobs, payload, checks_url=url)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    arguments.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if arguments.evidence_only or report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
