"""GitHub identity is independent of candidate receipts and remains exact at every edge."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from github_evidence_artifact import admit_artifact, artifact_inventory  # noqa: E402
from github_evidence_run import SQLITE, Selection, admit_run  # noqa: E402

from .hosted_evidence_fixtures import (  # noqa: E402
    COMMIT,
    RUN_PATH,
    SELECTED,
    EvidenceFixture,
    encoded,
    measured_fixture,
)


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> EvidenceFixture:
    return measured_fixture(tmp_path_factory.mktemp("github-identities"))


def _change(record: dict, path: tuple[str, ...], value) -> None:
    for name in path[:-1]:
        record = record[name]
    record[path[-1]] = value


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("repository", "id"), 1),
        (("repository", "owner", "id"), 1),
        (("repository", "full_name"), "foreign/KORPUS"),
        (("repository", "owner", "login"), "foreign"),
        (("head_repository", "id"), 1),
        (("head_repository", "owner", "id"), 1),
        (("workflow_id",), 1),
        (("path",), ".github/workflows/untrusted.yml"),
        (("id",), 999),
        (("run_attempt",), 1),
        (("run_attempt",), True),
        (("head_sha",), "f" * 40),
        (("head_branch",), "candidate"),
        (("event",), "pull_request"),
        (("event",), "workflow_dispatch"),
        (("status",), "in_progress"),
        (("conclusion",), "failure"),
    ],
)
def test_authenticated_run_fields_cannot_be_replaced_by_candidate_identity(
    measured: EvidenceFixture, path: tuple[str, ...], value
) -> None:
    fixture = measured.clone()
    fixture.replace_json(RUN_PATH, lambda record: _change(record, path, value))
    with pytest.raises(ValueError):
        admit_run(fixture.api, SELECTED, fixture.checkout)


def test_exact_attempt_response_is_checked_separately_from_latest(
    measured: EvidenceFixture,
) -> None:
    fixture = measured.clone()
    fixture.replace_json(
        RUN_PATH + f"/attempts/{SELECTED.attempt}",
        lambda record: record.update(run_attempt=1),
    )
    with pytest.raises(ValueError, match="run attempt mismatch"):
        admit_run(fixture.api, SELECTED, fixture.checkout)


def test_tree_comes_from_actual_checkout_not_run_report(measured: EvidenceFixture) -> None:
    fixture = measured.clone()
    fixture.replace_json(
        f"/git/commits/{COMMIT}", lambda record: record.update(tree={"sha": "f" * 40})
    )
    with pytest.raises(ValueError, match="checkout tree mismatch"):
        admit_run(fixture.api, SELECTED, fixture.checkout)


@pytest.mark.parametrize("selection", [(True, 2), (12345, True), (0, 2), (12345, 0)])
def test_run_selectors_have_exact_integer_types(selection: tuple) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        Selection(*selection)


def test_arbitrary_branch_and_tag_refs_are_outside_admission_policy() -> None:
    with pytest.raises(ValueError, match="only canonical main or explicit pull-request merge"):
        Selection(12345, 2, "refs/heads/candidate")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("run_attempt",), 1),
        (("run_attempt",), True),
        (("run_id",), 999),
        (("head_sha",), "f" * 40),
        (("head_branch",), "candidate"),
        (("conclusion",), "failure"),
        (("conclusion",), "skipped"),
        (("status",), "in_progress"),
        (("name",), "other-producer"),
        (("runner_group_name",), "self-hosted"),
        (("labels",), ["ubuntu-latest"]),
    ],
)
def test_named_producer_must_belong_to_successful_exact_hosted_attempt(
    measured: EvidenceFixture, path: tuple[str, ...], value
) -> None:
    fixture = measured.clone()
    endpoint = RUN_PATH + f"/attempts/{SELECTED.attempt}/jobs?per_page=100"
    fixture.replace_json(endpoint, lambda record: _change(record["jobs"][0], path, value))
    run = admit_run(fixture.api, SELECTED, fixture.checkout)
    with pytest.raises(ValueError):
        admit_artifact(fixture.api, run, SQLITE, artifact_inventory(fixture.api, run))


@pytest.mark.parametrize(
    "kind", ["incomplete", "duplicate_id", "duplicate_producer", "failed_upload"]
)
def test_job_collection_is_complete_unambiguous_and_uploaded_successfully(
    measured: EvidenceFixture, kind: str
) -> None:
    fixture = measured.clone()
    endpoint = RUN_PATH + f"/attempts/{SELECTED.attempt}/jobs?per_page=100"
    record = fixture.api.json(endpoint)
    if kind == "incomplete":
        record["total_count"] += 1
    elif kind == "failed_upload":
        record["jobs"][0]["steps"][0]["conclusion"] = "skipped"
    else:
        duplicate = copy.deepcopy(record["jobs"][0])
        if kind == "duplicate_producer":
            duplicate["id"] = 999
        record["jobs"].append(duplicate)
        record["total_count"] += 1
    fixture.api.responses[endpoint] = encoded(record)
    with pytest.raises(ValueError):
        run = admit_run(fixture.api, SELECTED, fixture.checkout)
        admit_artifact(fixture.api, run, SQLITE, artifact_inventory(fixture.api, run))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("id",), 999),
        (("name",), "api-coverage-diagnostics-1"),
        (("expired",), True),
        (("digest",), "sha256:" + "f" * 64),
        (("digest",), None),
        (("size_in_bytes",), True),
        (("workflow_run", "id"), 999),
        (("workflow_run", "repository_id"), 1),
        (("workflow_run", "head_repository_id"), 1),
        (("workflow_run", "head_sha"), "f" * 40),
        (("workflow_run", "head_branch"), "candidate"),
        (("created_at",), "2000-01-01T00:00:00Z"),
    ],
)
def test_artifact_identity_cannot_float_between_runs_jobs_or_attempts(
    measured: EvidenceFixture, path: tuple[str, ...], value
) -> None:
    fixture = measured.clone()
    endpoint = RUN_PATH + "/artifacts?per_page=100"
    fixture.replace_json(endpoint, lambda record: _change(record["artifacts"][0], path, value))
    run = admit_run(fixture.api, SELECTED, fixture.checkout)
    with pytest.raises(ValueError):
        admit_artifact(fixture.api, run, SQLITE, artifact_inventory(fixture.api, run))


def test_downloaded_zip_bytes_must_match_authenticated_digest(measured: EvidenceFixture) -> None:
    fixture = measured.clone()
    key = "/actions/artifacts/201/zip"
    payload = fixture.api.responses[key]
    assert payload.endswith(b"neutral artifact fixture")
    fixture.api.responses[key] = payload[:-1] + bytes([payload[-1] ^ 1])
    run = admit_run(fixture.api, SELECTED, fixture.checkout)
    with pytest.raises(ValueError, match="downloaded artifact SHA256 mismatch"):
        admit_artifact(fixture.api, run, SQLITE, artifact_inventory(fixture.api, run))


def test_successful_job_without_its_authenticated_upload_record_is_insufficient(
    measured: EvidenceFixture,
) -> None:
    fixture = measured.clone()
    key = "/actions/jobs/101/logs"
    fixture.api.responses[key] = fixture.api.responses[key].replace(
        b"Artifact ID 201", b"Artifact ID 999"
    )
    run = admit_run(fixture.api, SELECTED, fixture.checkout)
    with pytest.raises(ValueError, match="authenticated producer log"):
        admit_artifact(fixture.api, run, SQLITE, artifact_inventory(fixture.api, run))


def test_duplicate_api_json_is_not_an_authenticated_alternative(measured: EvidenceFixture) -> None:
    fixture = measured.clone()
    text = fixture.api.responses[RUN_PATH].decode()
    fixture.api.responses[RUN_PATH] = (text[:-1] + ',"id":12345}').encode()
    with pytest.raises(ValueError, match="duplicate key"):
        admit_run(fixture.api, SELECTED, fixture.checkout)


@pytest.mark.parametrize("poison", ["../outside.json", "COVERAGE.JSON"])
def test_coherent_unsafe_zip_is_rejected_before_member_use(
    measured: EvidenceFixture, poison: str
) -> None:
    fixture = measured.clone()
    fixture.members[SQLITE.job][poison] = b"{}"
    fixture.repack(SQLITE)
    run = admit_run(fixture.api, SELECTED, fixture.checkout)
    with pytest.raises(ValueError, match="unsafe GitHub artifact ZIP"):
        admit_artifact(fixture.api, run, SQLITE, artifact_inventory(fixture.api, run))


def test_admitted_member_bytes_do_not_follow_a_later_download_path_swap(
    measured: EvidenceFixture,
) -> None:
    fixture = measured.clone()
    run = admit_run(fixture.api, SELECTED, fixture.checkout)
    artifact = admit_artifact(fixture.api, run, SQLITE, artifact_inventory(fixture.api, run))
    original = artifact.members["coverage-sqlite-receipt.json"]
    fixture.api.responses["/actions/artifacts/201/zip"] = b"changed later"
    assert artifact.members["coverage-sqlite-receipt.json"] == original
    with pytest.raises(TypeError):
        artifact.members["coverage-sqlite-receipt.json"] = b"changed"
    assert json.loads(original)["status"] == "PASS"


def test_admitted_authority_is_unchanged_by_nested_mapping_or_original_api_mutation(
    measured: EvidenceFixture,
) -> None:
    fixture = measured.clone()
    run = admit_run(fixture.api, SELECTED, fixture.checkout)
    artifact = admit_artifact(fixture.api, run, SQLITE, artifact_inventory(fixture.api, run))
    expected = copy.deepcopy(artifact.receipt)
    run_metadata = run.metadata
    run_metadata["repository"]["owner"]["id"] = 1
    jobs = run.jobs
    jobs[0]["steps"].clear()
    artifact_metadata = artifact.metadata
    artifact_metadata["workflow_run"]["id"] = 1
    artifact_job = artifact.job
    artifact_job["steps"][0]["conclusion"] = "failure"
    source = run.checkout.source
    source["files"].clear()
    source["inputs"].clear()
    fixture.artifacts[SQLITE.job]["id"] = 1
    fixture.jobs[SQLITE.job]["steps"].clear()
    assert artifact.receipt == expected
    assert run.metadata["repository"]["owner"]["id"] != 1
    assert run.jobs[0]["steps"] and run.checkout.source["files"] and run.checkout.source["inputs"]
