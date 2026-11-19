"""Fixed repository/workflow policy for completed canonical push and PR CI attempts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from coverage_execution_contract import canonical_bytes
from github_evidence_base import BaseAuthority, observe_pr_base, stable_pr_base
from github_evidence_source import Checkout
from github_evidence_transport import GitHubTransport, insist, object_record, object_records
from korpus.application.github_release_context import (
    CANONICAL_GITHUB_OWNER_ID,
    CANONICAL_GITHUB_REPOSITORY,
    CANONICAL_GITHUB_REPOSITORY_ID,
    GIT_SHA,
)

WORKFLOW_ID = 332983285
WORKFLOW_PATH = ".github/workflows/ci.yml"
UPLOAD_ACTION = "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9"
REPOSITORY_ID = int(CANONICAL_GITHUB_REPOSITORY_ID)
OWNER_ID = int(CANONICAL_GITHUB_OWNER_ID)


@dataclass(frozen=True)
class Selection:
    run_id: int
    attempt: int
    ref: str = "refs/heads/main"

    def __post_init__(self) -> None:
        insist(type(self.run_id) is int and self.run_id > 0, "run ID must be a positive integer")
        insist(type(self.attempt) is int and self.attempt > 0, "attempt must be a positive integer")
        insist(
            self.ref == "refs/heads/main"
            or re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", self.ref) is not None,
            "only canonical main or explicit pull-request merge evidence is admitted",
        )


@dataclass(frozen=True)
class Producer:
    artifact_prefix: str
    job: str
    upload_step: str
    required_members: tuple[str, ...]


SQLITE = Producer(
    "api-coverage-diagnostics",
    "api-tests",
    "Preserve API and coverage diagnostics",
    (
        "coverage-sqlite.data",
        "coverage.json",
        "coverage-sqlite-receipt.json",
        "coverage-union.json",
    ),
)
POSTGRES = Producer(
    "coverage-postgres",
    "assurance / postgres-full-suite",
    "Upload PostgreSQL coverage evidence",
    ("coverage-postgres.data", "coverage-postgres.json", "coverage-postgres-receipt.json"),
)
SECURITY = Producer(
    "source-security-evidence",
    "source-security",
    "Upload source security evidence",
    ("tree-sbom.cdx.json", "source-security-receipt.json"),
)
PACKAGE = Producer(
    "canonical-package",
    "canonical-package",
    "Upload verified source package",
    (
        "var/package-first-verification.json",
        "var/package-second-verification.json",
        "var/package-envelope.json",
    ),
)


def timestamp(value: Any) -> float:
    insist(isinstance(value, str), "GitHub execution timestamp is missing")
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    insist(instant.utcoffset() is not None, "execution timestamp must include its timezone")
    return instant.timestamp()


def exact_integer(value: Any, expected: int, label: str) -> None:
    insist(type(value) is int and value == expected, f"{label} mismatch")


def repository(record: Any) -> None:
    insist(isinstance(record, dict), "canonical repository metadata is missing")
    exact_integer(record.get("id"), REPOSITORY_ID, "repository numeric ID")
    insist(record.get("full_name") == CANONICAL_GITHUB_REPOSITORY, "repository name mismatch")
    owner = record.get("owner")
    insist(isinstance(owner, dict), "canonical owner metadata is missing")
    exact_integer(owner.get("id"), OWNER_ID, "repository owner numeric ID")
    insist(owner.get("login") == CANONICAL_GITHUB_REPOSITORY.split("/")[0], "owner name mismatch")


def successful(record: dict[str, Any], label: str) -> None:
    insist(
        record.get("status") == "completed" and record.get("conclusion") == "success",
        f"{label} must be completed and successful",
    )


def validate_run(record: dict[str, Any], selected: Selection, checkout: Checkout) -> None:
    repository(record.get("repository"))
    repository(record.get("head_repository"))
    exact_integer(record.get("id"), selected.run_id, "run ID")
    exact_integer(record.get("run_attempt"), selected.attempt, "run attempt")
    exact_integer(record.get("workflow_id"), WORKFLOW_ID, "workflow numeric ID")
    insist(record.get("path") == WORKFLOW_PATH, "workflow path is not allowlisted")
    head_sha = record.get("head_sha")
    insist(
        isinstance(head_sha, str) and GIT_SHA.fullmatch(head_sha) is not None,
        "invalid run head SHA",
    )
    if selected.ref == "refs/heads/main":
        insist(record.get("event") == "push", "main evidence must come from a push execution")
        insist(record.get("head_branch") == "main", "run ref differs from canonical main")
        insist(record.get("head_sha") == checkout.commit, "run head differs from actual checkout")
    else:
        insist(
            record.get("event") == "pull_request",
            "PR evidence must come from a pull-request execution",
        )
    successful(record, "workflow run")


def _pull_request_subject(
    api: GitHubTransport,
    selected: Selection,
    checkout: Checkout,
    run: dict[str, Any],
    commit: dict[str, Any],
) -> BaseAuthority:
    number = int(selected.ref.split("/")[2])
    pull = api.json(f"/pulls/{number}")
    exact_integer(pull.get("number"), number, "pull-request number")
    head = object_record(pull.get("head"), "PR head metadata missing")
    base = object_record(pull.get("base"), "PR base metadata missing")
    repository(head.get("repo"))
    repository(base.get("repo"))
    insist(head.get("sha") == run.get("head_sha"), "PR head differs from run head")
    insist(head.get("ref") == run.get("head_branch"), "PR branch differs from run head branch")
    authority = observe_pr_base(api, pull)
    insist(pull.get("merge_commit_sha") == checkout.commit, "PR merge differs from actual checkout")
    parents = commit.get("parents")
    insist(
        isinstance(parents, list)
        and len(parents) == 2
        and all(isinstance(parent, dict) for parent in parents)
        and [parent.get("sha") for parent in parents] == [authority.sha, head.get("sha")],
        "checkout commit is not the exact PR base/head merge",
    )
    references = run.get("referenced_workflows")
    expected = {
        "path": f"{CANONICAL_GITHUB_REPOSITORY}/.github/workflows/assurance.yml@{checkout.commit}",
        "sha": checkout.commit,
        "ref": selected.ref,
    }
    insist(
        isinstance(references, list)
        and sum(reference == expected for reference in references) == 1,
        "run does not prove the selected PR merge checkout/ref",
    )
    return authority


@dataclass(frozen=True)
class AdmittedRun:
    selected: Selection
    checkout: Checkout
    metadata_bytes: bytes
    jobs_bytes: bytes

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(json.loads(self.metadata_bytes))

    @property
    def jobs(self) -> tuple[dict[str, Any], ...]:
        return tuple(json.loads(self.jobs_bytes))

    @property
    def receipt_run(self) -> dict[str, str]:
        return {
            "kind": "github-actions",
            "GITHUB_REPOSITORY": CANONICAL_GITHUB_REPOSITORY,
            "GITHUB_SHA": self.checkout.commit,
            "GITHUB_RUN_ID": str(self.selected.run_id),
            "GITHUB_RUN_ATTEMPT": str(self.selected.attempt),
        }


def admit_run(api: GitHubTransport, selected: Selection, checkout: Checkout) -> AdmittedRun:
    path = f"/actions/runs/{selected.run_id}"
    # The latest-attempt lookup prevents an older successful attempt laundering a rerun.
    validate_run(api.json(path), selected, checkout)
    run = api.json(f"{path}/attempts/{selected.attempt}")
    validate_run(run, selected, checkout)
    commit = api.json(f"/git/commits/{checkout.commit}")
    insist(commit.get("sha") == checkout.commit, "GitHub commit response changed its subject")
    tree = commit.get("tree")
    insist(isinstance(tree, dict) and tree.get("sha") == checkout.tree, "checkout tree mismatch")
    subject = None
    if selected.ref != "refs/heads/main":
        subject = _pull_request_subject(api, selected, checkout, run, commit)
    jobs = api.collection(f"{path}/attempts/{selected.attempt}/jobs", "jobs")
    identifiers = [job.get("id") for job in jobs]
    insist(
        all(type(value) is int and value > 0 for value in identifiers)
        and len(set(identifiers)) == len(identifiers),
        "GitHub job collection contains invalid or duplicate IDs",
    )
    if subject is not None:
        stable_pr_base(api, subject)
    return AdmittedRun(selected, checkout, canonical_bytes(run), canonical_bytes(jobs))


def producer_job(run: AdmittedRun, producer: Producer) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = [job for job in run.jobs if job.get("name") == producer.job]
    insist(len(matches) == 1, f"required producer job missing or duplicated: {producer.job}")
    job = matches[0]
    exact_integer(job.get("run_id"), run.selected.run_id, "producer run ID")
    exact_integer(job.get("run_attempt"), run.selected.attempt, "producer run attempt")
    insist(job.get("head_sha") == run.metadata["head_sha"], "producer commit mismatch")
    insist(job.get("head_branch") == run.metadata["head_branch"], "producer branch mismatch")
    insist(
        job.get("runner_group_name") == "GitHub Actions" and job.get("labels") == ["ubuntu-24.04"],
        "producer did not use the fixed GitHub hosted runner",
    )
    successful(job, producer.job)
    steps = object_records(job.get("steps"), "invalid job steps")
    uploads = [step for step in steps if step.get("name") == producer.upload_step]
    insist(len(uploads) == 1, "required producer upload step is missing or duplicated")
    upload = uploads[0]
    successful(upload, producer.upload_step)
    insist(
        timestamp(job.get("started_at"))
        <= timestamp(upload.get("started_at"))
        <= timestamp(upload.get("completed_at"))
        <= timestamp(job.get("completed_at")),
        "producer upload timestamps are outside the job",
    )
    return job, upload
