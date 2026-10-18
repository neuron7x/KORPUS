#!/usr/bin/env python3
"""Import scanner artifacts from one exact successful canonical Actions run."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from github_actions_evidence import (  # noqa: E402
    SCANNER_PRODUCER_JOBS,
    ArtifactRequest,
    DownloadRequest,
    RunIdentity,
    ScannerRunEvidence,
    fetch_exact_run,
    fetch_run_artifacts,
    job_receipts,
    successful_run_problem,
)
from source_digest import commits_with_identical_source  # noqa: E402

DEFAULT_REPOSITORY = "neuron7x/KORPUS"
CANONICAL_WORKFLOW = ".github/workflows/assurance.yml"
OUT = ROOT / "var/security"

ARTIFACTS = {
    "security-gitleaks": "ci-gitleaks.json",
    "security-pip-audit": "ci-pip-audit.json",
    "security-trivy": "ci-trivy.json",
    "security-summary": "summary.json",
    "container-security": "ci-container-scan.json",
}
PRODUCER_JOBS = SCANNER_PRODUCER_JOBS


def _gh_bytes(endpoint: str) -> bytes:
    result = subprocess.run(
        [
            "gh",
            "api",
            "--header",
            "Accept: application/vnd.github+json",
            endpoint,
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[:200]
        raise SystemExit(f"gh api {endpoint}: {detail}")
    return result.stdout


def artifact_file(request: ArtifactRequest) -> bytes | None:
    """Return one declared file from an artifact ZIP, without extracting other paths."""

    archive = _gh_bytes(f"repos/{request.repository}/actions/artifacts/{request.artifact_id}/zip")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            matches = [name for name in bundle.namelist() if Path(name).name == request.file_name]
            if len(matches) != 1:
                return None
            return bundle.read(matches[0])
    except (zipfile.BadZipFile, KeyError):
        return None


def _refused_files(reason: str) -> dict[str, str]:
    return {file_name: reason for file_name in ARTIFACTS.values()}


def _current_artifact(
    context: tuple[list[dict[str, Any]], str, str, int, str],
) -> tuple[dict[str, Any] | None, str | None]:
    artifacts, artifact_name, run_started_at, run_id, head_sha = context
    candidates = [
        item
        for item in artifacts
        if item.get("name") == artifact_name
        and run_started_at
        and str(item.get("created_at", "")) >= run_started_at
        and isinstance(item.get("workflow_run"), dict)
        and item["workflow_run"].get("id") == run_id
        and item["workflow_run"].get("head_sha") == head_sha
    ]
    if len(candidates) != 1:
        return None, f"has {len(candidates)} current-attempt candidates"
    artifact = candidates[0]
    if artifact.get("expired") is not False:
        return None, "is expired"
    if not isinstance(artifact.get("id"), int) or isinstance(artifact.get("id"), bool):
        return None, "has no numeric id"
    return artifact, None


def _available_artifacts(
    context: tuple[list[dict[str, Any]], str, str, int],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    artifacts, head_sha, run_started_at, run_id = context
    fetched: dict[str, dict[str, Any]] = {}
    refused: dict[str, str] = {}
    for artifact_name, file_name in ARTIFACTS.items():
        artifact, problem = _current_artifact(
            (artifacts, artifact_name, run_started_at, run_id, head_sha)
        )
        if artifact is None or problem is not None:
            refused[file_name] = f"artifact {artifact_name} {problem or 'is invalid'}"
            continue
        fetched[file_name] = {
            "artifact": artifact_name,
            "artifact_id": artifact["id"],
            "commit": head_sha,
        }
    return fetched, refused


def _run_problem(source: ScannerRunEvidence) -> str | None:
    run, accepted = source.metadata, source.accepted_commits
    run_id, attempt = run.get("id"), run.get("run_attempt")
    if source.repository != DEFAULT_REPOSITORY:
        return f"repository is {source.repository}, not {DEFAULT_REPOSITORY}"
    if not isinstance(run_id, int) or not isinstance(attempt, int):
        return "run/attempt identity is absent"
    head_sha = str(run.get("head_sha", ""))
    if head_sha not in accepted:
        return f"run head {head_sha[:12]} is not source-identical to HEAD"
    identity = RunIdentity(
        source.repository,
        CANONICAL_WORKFLOW,
        "pull_request",
        source.workflow_id,
        head_sha,
        run_id,
        attempt,
    )
    problem: str | None = successful_run_problem(
        run, identity, source.latest_run_id, source.jobs, PRODUCER_JOBS
    )
    return problem


def _base_report(source: ScannerRunEvidence) -> dict[str, Any]:
    run, accepted = source.metadata, source.accepted_commits
    head_sha = str(run.get("head_sha", ""))
    return {
        "schema": "korpus.ci-scanner-marker-fetch.v3",
        "provider": "github-actions",
        "repository": source.repository,
        "workflow_path": CANONICAL_WORKFLOW,
        "workflow_id": source.workflow_id,
        "event": run.get("event"),
        "run_id": run.get("id", "UNKNOWN"),
        "attempt": run.get("run_attempt", "UNKNOWN"),
        "head_ref": run.get("head_branch", "UNKNOWN"),
        "head_sha": head_sha,
        "producer_jobs": job_receipts(source.jobs, PRODUCER_JOBS),
        "accepted_commits": sorted(accepted),
        "fetched": {},
        "refused": {},
    }


def verdict(source: ScannerRunEvidence) -> dict[str, Any]:
    run, artifacts = source.metadata, source.artifacts
    head_sha = str(run.get("head_sha", ""))
    report = _base_report(source)
    if problem := _run_problem(source):
        report["refused"] = _refused_files(problem)
        return report
    report["fetched"], report["refused"] = _available_artifacts(
        (artifacts, head_sha, str(run.get("run_started_at", "")), int(run["id"]))
    )
    return report


def _bound_payload(subject: tuple[bytes, frozenset[str], str]) -> bool:
    payload, accepted, head_sha = subject
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return (
        isinstance(value, dict)
        and value.get("commit_sha") == head_sha
        and value.get("commit_sha") in accepted
    )


def _write_selected(request: DownloadRequest) -> list[str]:
    if request.write:
        OUT.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    report = request.report
    for file_name, meta in list(report["fetched"].items()):
        payload = artifact_file(
            ArtifactRequest(request.repository, int(meta["artifact_id"]), file_name)
        )
        if payload is None:
            report["refused"][file_name] = f"{meta['artifact']}: declared file is absent"
            del report["fetched"][file_name]
            continue
        if not _bound_payload((payload, request.accepted_commits, str(report["head_sha"]))):
            report["refused"][file_name] = (
                f"{meta['artifact']}: payload commit is not the admitted run head"
            )
            del report["fetched"][file_name]
            continue
        if request.write:
            (OUT / file_name).write_bytes(payload)
            written.append(file_name)
    return written


def _admitted_source(run_id: int, accepted: frozenset[str]) -> ScannerRunEvidence:
    exact = fetch_exact_run(ROOT, DEFAULT_REPOSITORY, CANONICAL_WORKFLOW, run_id)
    if exact is None:
        raise SystemExit("GitHub run/workflow/jobs API evidence is partial or invalid")
    return ScannerRunEvidence(
        DEFAULT_REPOSITORY,
        exact.workflow_id,
        exact.latest_run_id,
        exact.run,
        exact.jobs,
        [],
        accepted,
    )


def _finish(source: ScannerRunEvidence, *, write: bool) -> int:
    report = verdict(source)
    report["written"] = _write_selected(
        DownloadRequest(source.repository, source.accepted_commits, report, write)
    )
    report["status"] = (
        "PASS" if len(report["fetched"]) == len(ARTIFACTS) and not report["refused"] else "PARTIAL"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=int, help="GitHub Actions run id")
    parser.add_argument(
        "--repo", choices=(DEFAULT_REPOSITORY,), default=DEFAULT_REPOSITORY, help="canonical repo"
    )
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    accepted = frozenset(commits_with_identical_source())
    if not accepted:
        raise SystemExit("empty accepted-commit set: no scanner evidence can be admitted")
    admitted = _admitted_source(arguments.run, accepted)
    if _run_problem(admitted):
        report = verdict(admitted)
        report["status"] = "PARTIAL"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    artifacts = fetch_run_artifacts(ROOT, arguments.repo, arguments.run)
    source = admitted._replace(artifacts=artifacts or [])
    return _finish(source, write=not arguments.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
