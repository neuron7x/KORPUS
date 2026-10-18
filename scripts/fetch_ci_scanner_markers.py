#!/usr/bin/env python3
"""Fetch scanner evidence from one GitHub Actions run and bind it to this tree.

The canonical scanner producers are jobs in ``.github/workflows/assurance.yml``.
GitHub artifacts are scoped to a workflow run rather than a job, so this importer
checks both layers that identify their subject: the run's immutable ``head_sha`` and
the ``commit_sha`` inside every downloaded JSON payload.  A missing artifact, an
expired artifact, a non-completed run, or either SHA outside the set of commits whose
source is identical to ``HEAD`` is a refusal.

The script copies bytes only after those checks.  It never creates, repairs, or merges
scanner results; the production predicate remains the consumer of the downloaded
evidence.

    fetch_ci_scanner_markers.py --run 123456789
    fetch_ci_scanner_markers.py --run 123456789 --dry-run
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from source_digest import commits_with_identical_source  # noqa: E402

DEFAULT_REPOSITORY = "neuron7x/KORPUS"
CANONICAL_WORKFLOW = ".github/workflows/assurance.yml"
OUT = ROOT / "var/security"

# Artifact name -> file carried inside it.  The set is closed: adding a scanner or
# changing an artifact boundary must update the importer and its tests explicitly.
ARTIFACTS = {
    "security-gitleaks": "ci-gitleaks.json",
    "security-pip-audit": "ci-pip-audit.json",
    "security-trivy": "ci-trivy.json",
    "security-summary": "summary.json",
    "container-security": "ci-container-scan.json",
}


class EvidenceRun(NamedTuple):
    metadata: dict[str, Any]
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


def _gh_json(endpoint: str) -> dict[str, Any]:
    result = subprocess.run(
        ["gh", "api", endpoint],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"gh api {endpoint}: {result.stderr.strip()[:200]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"gh api {endpoint}: response is not JSON") from error
    if not isinstance(payload, dict):
        raise SystemExit(f"gh api {endpoint}: expected an object")
    return payload


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


def run_metadata(repository: str, run_id: str) -> dict[str, Any]:
    metadata = _gh_json(f"repos/{repository}/actions/runs/{run_id}")
    attempt = metadata.get("run_attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        return metadata
    return _gh_json(f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}")


def run_artifacts(repository: str, run_id: str) -> list[dict[str, Any]]:
    payload = _gh_json(f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise SystemExit("GitHub artifacts response has no artifact list")
    return [item for item in artifacts if isinstance(item, dict)]


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
    context: tuple[list[dict[str, Any]], str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    artifacts, artifact_name, run_started_at = context
    candidates = [
        item
        for item in artifacts
        if item.get("name") == artifact_name
        and run_started_at
        and str(item.get("created_at", "")) >= run_started_at
    ]
    if len(candidates) != 1:
        return None, f"has {len(candidates)} current-attempt candidates"
    artifact = candidates[0]
    if artifact.get("expired") is True:
        return None, "is expired"
    if not isinstance(artifact.get("id"), int) or isinstance(artifact.get("id"), bool):
        return None, "has no numeric id"
    return artifact, None


def _available_artifacts(
    context: tuple[list[dict[str, Any]], str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    artifacts, head_sha, run_started_at = context
    fetched: dict[str, dict[str, Any]] = {}
    refused: dict[str, str] = {}
    for artifact_name, file_name in ARTIFACTS.items():
        artifact, problem = _current_artifact((artifacts, artifact_name, run_started_at))
        if artifact is None or problem is not None:
            refused[file_name] = f"artifact {artifact_name} {problem or 'is invalid'}"
            continue
        fetched[file_name] = {
            "artifact": artifact_name,
            "artifact_id": artifact["id"],
            "commit": head_sha,
        }
    return fetched, refused


def _run_problem(context: tuple[dict[str, Any], frozenset[str]]) -> str | None:
    run, accepted = context
    if run.get("path") != CANONICAL_WORKFLOW:
        return f"run workflow is {run.get('path', 'UNKNOWN')}, not {CANONICAL_WORKFLOW}"
    if run.get("status") != "completed":
        return f"run is {run.get('status', 'UNKNOWN')}, not completed"
    head_sha = str(run.get("head_sha", ""))
    if head_sha not in accepted:
        return f"run head {head_sha[:12]} is not source-identical to HEAD"
    return None


def verdict(source: EvidenceRun) -> dict[str, Any]:
    run, artifacts, accepted = source
    head_sha = str(run.get("head_sha", ""))
    report: dict[str, Any] = {
        "schema": "korpus.ci-scanner-marker-fetch.v2",
        "provider": "github-actions",
        "run_id": str(run.get("id", "UNKNOWN")),
        "head_sha": head_sha,
        "accepted_commits": sorted(accepted),
        "fetched": {},
        "refused": {},
    }
    if problem := _run_problem((run, accepted)):
        report["refused"] = _refused_files(problem)
        return report
    report["fetched"], report["refused"] = _available_artifacts(
        (artifacts, head_sha, str(run.get("run_started_at", "")))
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="GitHub Actions run id")
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY, help="OWNER/REPOSITORY")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    accepted = frozenset(commits_with_identical_source())
    if not accepted:
        raise SystemExit("empty accepted-commit set: no scanner evidence can be admitted")
    run = run_metadata(arguments.repo, arguments.run)
    report = verdict(EvidenceRun(run, run_artifacts(arguments.repo, arguments.run), accepted))

    report["written"] = _write_selected(
        DownloadRequest(arguments.repo, accepted, report, not arguments.dry_run)
    )
    report["status"] = (
        "PASS" if len(report["fetched"]) == len(ARTIFACTS) and not report["refused"] else "PARTIAL"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
