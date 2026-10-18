from __future__ import annotations

import importlib.util
import io
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/fetch_ci_scanner_markers.py"
SPEC = importlib.util.spec_from_file_location("fetch_ci_scanner_markers", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)


def _artifacts() -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "id": index,
            "expired": False,
            "created_at": "2026-10-19T12:01:00Z",
        }
        for index, name in enumerate(fetch.ARTIFACTS, start=1)
    ]


def test_make_entrypoint_names_the_github_run_not_a_gitlab_pipeline() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("ci-scanner-markers:", 1)[1].split("\n\n", 1)[0]
    assert '--run "$(RUN)"' in recipe
    assert "--pipeline" not in recipe


def test_complete_github_run_exposes_the_exact_closed_artifact_set() -> None:
    commit = "a" * 40
    report = fetch.verdict(
        fetch.EvidenceRun(
            {
                "id": 7,
                "status": "completed",
                "head_sha": commit,
                "path": fetch.CANONICAL_WORKFLOW,
                "run_started_at": "2026-10-19T12:00:00Z",
            },
            _artifacts(),
            frozenset({commit}),
        )
    )

    assert report["provider"] == "github-actions"
    assert set(report["fetched"]) == set(fetch.ARTIFACTS.values())
    assert report["refused"] == {}


def test_nonidentical_or_incomplete_run_refuses_every_artifact() -> None:
    report = fetch.verdict(
        fetch.EvidenceRun(
            {
                "id": 8,
                "status": "in_progress",
                "head_sha": "b" * 40,
                "path": fetch.CANONICAL_WORKFLOW,
                "run_started_at": "2026-10-19T12:00:00Z",
            },
            _artifacts(),
            frozenset({"a" * 40}),
        )
    )

    assert report["fetched"] == {}
    assert set(report["refused"]) == set(fetch.ARTIFACTS.values())


def test_another_workflow_or_previous_attempt_cannot_supply_canonical_markers() -> None:
    commit = "a" * 40
    run = {
        "id": 9,
        "status": "completed",
        "head_sha": commit,
        "path": ".github/workflows/ci.yml",
        "run_started_at": "2026-10-19T12:00:00Z",
    }
    wrong_workflow = fetch.verdict(fetch.EvidenceRun(run, _artifacts(), frozenset({commit})))
    assert wrong_workflow["fetched"] == {}

    run["path"] = fetch.CANONICAL_WORKFLOW
    stale = _artifacts()
    for artifact in stale:
        artifact["created_at"] = "2026-10-19T11:59:59Z"
    previous_attempt = fetch.verdict(fetch.EvidenceRun(run, stale, frozenset({commit})))
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
    report = fetch.verdict(
        fetch.EvidenceRun(
            {
                "id": 10,
                "status": "completed",
                "head_sha": commit,
                "path": fetch.CANONICAL_WORKFLOW,
                "run_started_at": "2026-10-19T12:00:00Z",
            },
            _artifacts(),
            frozenset({commit}),
        )
    )
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
