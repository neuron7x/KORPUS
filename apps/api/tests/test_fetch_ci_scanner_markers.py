from __future__ import annotations

import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/fetch_ci_scanner_markers.py"
SPEC = importlib.util.spec_from_file_location("fetch_ci_scanner_markers", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)
import github_actions_evidence as gha  # noqa: E402


def _artifacts(commit: str, run_id: int = 7) -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "id": index,
            "expired": False,
            "created_at": "2026-10-19T12:01:00Z",
            "workflow_run": {"id": run_id, "head_sha": commit},
        }
        for index, name in enumerate(fetch.ARTIFACTS, start=1)
    ]


def _metadata(commit: str, run_id: int = 7, **changes: object) -> dict[str, object]:
    repository = fetch.DEFAULT_REPOSITORY
    branch = "work/issue-54"
    value: dict[str, object] = {
        "id": run_id,
        "run_number": run_id,
        "run_attempt": 2,
        "workflow_id": 42,
        "status": "completed",
        "conclusion": "success",
        "head_sha": commit,
        "head_branch": branch,
        "event": "pull_request",
        "path": fetch.CANONICAL_WORKFLOW,
        "repository": {"full_name": repository},
        "head_repository": {"full_name": repository},
        "pull_requests": [
            {
                "head": {
                    "sha": commit,
                    "ref": branch,
                    "repo": {"url": f"https://api.github.com/repos/{repository}"},
                },
                "base": {"repo": {"url": f"https://api.github.com/repos/{repository}"}},
            }
        ],
        "run_started_at": "2026-10-19T12:00:00Z",
    }
    value.update(changes)
    return value


def _jobs(commit: str, run_id: int = 7, attempt: int = 2) -> list[dict[str, object]]:
    return [
        {
            "id": index,
            "name": name,
            "run_id": run_id,
            "run_attempt": attempt,
            "head_sha": commit,
            "status": "completed",
            "conclusion": "success",
        }
        for index, name in enumerate(sorted(fetch.PRODUCER_JOBS), start=1)
    ]


def _source(commit: str, **run_changes: object) -> object:
    run = _metadata(commit, **run_changes)
    run_id, attempt = int(run["id"]), int(run["run_attempt"])
    return fetch.ScannerRunEvidence(
        fetch.DEFAULT_REPOSITORY,
        42,
        run_id,
        run,
        _jobs(commit, run_id, attempt),
        _artifacts(commit, run_id),
        frozenset({commit}),
    )


def test_make_entrypoint_names_the_github_run_not_a_gitlab_pipeline() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("ci-scanner-markers:", 1)[1].split("\n\n", 1)[0]
    assert '--run "$(RUN)"' in recipe
    assert "--pipeline" not in recipe


def test_complete_github_run_exposes_the_exact_closed_artifact_set() -> None:
    commit = "a" * 40
    report = fetch.verdict(_source(commit))

    assert report["provider"] == "github-actions"
    assert report["repository"] == "neuron7x/KORPUS"
    assert report["workflow_id"] == 42
    assert report["attempt"] == 2
    assert set(report["fetched"]) == set(fetch.ARTIFACTS.values())
    assert report["refused"] == {}


def test_nonidentical_or_incomplete_run_refuses_every_artifact() -> None:
    commit = "b" * 40
    source = _source(commit, status="in_progress", conclusion=None)
    report = fetch.verdict(source._replace(accepted_commits=frozenset({"a" * 40})))

    assert report["fetched"] == {}
    assert set(report["refused"]) == set(fetch.ARTIFACTS.values())


def test_another_workflow_or_previous_attempt_cannot_supply_canonical_markers() -> None:
    commit = "a" * 40
    wrong_workflow = fetch.verdict(_source(commit, path=".github/workflows/ci.yml"))
    assert wrong_workflow["fetched"] == {}

    source = _source(commit)
    stale = _artifacts(commit)
    for artifact in stale:
        artifact["created_at"] = "2026-10-19T11:59:59Z"
    previous_attempt = fetch.verdict(source._replace(artifacts=stale))
    assert previous_attempt["fetched"] == {}
    assert set(previous_attempt["refused"]) == set(fetch.ARTIFACTS.values())


def test_payload_must_name_the_same_admitted_run_head() -> None:
    commit = "c" * 40
    accepted = frozenset({commit})
    assert fetch._bound_payload((json.dumps({"commit_sha": commit}).encode(), accepted, commit))
    assert not fetch._bound_payload(
        (json.dumps({"commit_sha": "d" * 40}).encode(), accepted, commit)
    )
    assert not fetch._bound_payload((b"not-json", accepted, commit))


def test_artifact_reader_refuses_duplicate_declared_filenames(monkeypatch) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("one/summary.json", "{}")
        bundle.writestr("two/summary.json", "{}")
    monkeypatch.setattr(fetch, "_gh_bytes", lambda _endpoint: archive.getvalue())

    assert fetch.artifact_file(fetch.ArtifactRequest("neuron7x/KORPUS", 1, "summary.json")) is None


def test_dry_run_validates_payloads_without_writing_them(tmp_path: Path, monkeypatch) -> None:
    commit = "e" * 40
    report = fetch.verdict(_source(commit))
    monkeypatch.setattr(fetch, "OUT", tmp_path / "security")
    monkeypatch.setattr(
        fetch,
        "artifact_file",
        lambda _request: json.dumps({"commit_sha": commit}).encode(),
    )

    written = fetch._write_selected(
        fetch.DownloadRequest("neuron7x/KORPUS", frozenset({commit}), report, False)
    )

    assert written == []
    assert report["refused"] == {}
    assert not fetch.OUT.exists()


def test_arbitrary_repo_failed_run_or_non_pr_event_is_never_credited() -> None:
    commit = "f" * 40
    source = _source(commit)
    assert fetch.verdict(source._replace(repository="attacker/fork"))["fetched"] == {}
    assert fetch.verdict(_source(commit, conclusion="failure"))["fetched"] == {}
    assert fetch.verdict(_source(commit, event="workflow_dispatch"))["fetched"] == {}


def test_stale_attempt_latest_run_or_foreign_head_repo_is_never_credited() -> None:
    commit = "1" * 40
    source = _source(commit)
    stale_jobs = [dict(job, run_attempt=1) for job in source.jobs]
    assert fetch.verdict(source._replace(jobs=stale_jobs))["fetched"] == {}
    assert fetch.verdict(source._replace(latest_run_id=999))["fetched"] == {}
    assert (
        fetch.verdict(_source(commit, head_repository={"full_name": "attacker/fork"}))["fetched"]
        == {}
    )


def test_missing_failed_or_duplicate_producer_job_is_never_credited() -> None:
    commit = "2" * 40
    source = _source(commit)
    assert fetch.verdict(source._replace(jobs=source.jobs[:-1]))["fetched"] == {}
    failed = [*source.jobs]
    failed[0] = dict(failed[0], conclusion="failure")
    assert fetch.verdict(source._replace(jobs=failed))["fetched"] == {}
    duplicate = [*source.jobs, dict(source.jobs[0], id=999)]
    assert fetch.verdict(source._replace(jobs=duplicate))["fetched"] == {}


def test_rejected_producers_prevent_artifact_api_access(monkeypatch, capsys) -> None:
    commit = "3" * 40
    run = _metadata(commit, conclusion="failure")
    monkeypatch.setattr(fetch, "commits_with_identical_source", lambda: [commit])
    exact = SimpleNamespace(workflow_id=42, latest_run_id=7, run=run, jobs=_jobs(commit))
    monkeypatch.setattr(fetch, "fetch_exact_run", lambda *_args: exact)
    monkeypatch.setattr(
        fetch,
        "fetch_run_artifacts",
        lambda *_args: (_ for _ in ()).throw(AssertionError("artifact API reached")),
    )
    monkeypatch.setattr(
        sys, "argv", [str(fetch.SCRIPT if hasattr(fetch, "SCRIPT") else SCRIPT), "--run", "7"]
    )

    assert fetch.main() == 1
    assert '"status": "PARTIAL"' in capsys.readouterr().out


def test_exact_run_fetch_refuses_api_failure_partial_jobs_and_wrong_workflow(monkeypatch) -> None:
    commit = "4" * 40
    run = _metadata(commit)
    repo, path = fetch.DEFAULT_REPOSITORY, fetch.CANONICAL_WORKFLOW
    endpoints: dict[str, object] = {
        f"repos/{repo}/actions/runs/7": run,
        f"repos/{repo}/actions/runs/7/attempts/2": run,
        f"repos/{repo}/actions/workflows?per_page=100": {
            "total_count": 1,
            "workflows": [{"id": 42, "path": path, "state": "active"}],
        },
        f"repos/{repo}/actions/workflows/42/runs?head_sha={commit}&event=pull_request&per_page=100": {
            "total_count": 1,
            "workflow_runs": [run],
        },
        f"repos/{repo}/actions/runs/7/attempts/2/jobs?per_page=100": {
            "total_count": len(fetch.PRODUCER_JOBS) + 1,
            "jobs": _jobs(commit),
        },
    }
    monkeypatch.setattr(gha, "_gh_api", lambda _root, endpoint: endpoints.get(endpoint))
    assert gha.fetch_exact_run(ROOT, repo, path, 7) is None

    endpoints[f"repos/{repo}/actions/runs/7/attempts/2/jobs?per_page=100"] = {
        "total_count": len(fetch.PRODUCER_JOBS),
        "jobs": _jobs(commit),
    }
    assert gha.fetch_exact_run(ROOT, repo, path, 7) is not None
    endpoints[f"repos/{repo}/actions/workflows?per_page=100"] = {
        "total_count": 1,
        "workflows": [{"id": 42, "path": ".github/workflows/other.yml", "state": "active"}],
    }
    assert gha.fetch_exact_run(ROOT, repo, path, 7) is None
    endpoints[f"repos/{repo}/actions/workflows?per_page=100"] = None
    assert gha.fetch_exact_run(ROOT, repo, path, 7) is None
