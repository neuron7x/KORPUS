"""Bounded discovery of the independent CI run for this exact checkout and event ref."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from github_evidence_run import WORKFLOW_ID, WORKFLOW_PATH, Selection, repository
from github_evidence_source import Checkout, capture_checkout
from github_evidence_transport import GitHubEvidenceError, GitHubTransport, insist, object_record
from korpus.application.github_release_context import GIT_SHA

MAX_WAIT_SECONDS = 3600
POLL_SECONDS = 15
MAX_POLLS = 240


def _head(api: GitHubTransport, checkout: Checkout, ref: str) -> str:
    Selection(1, 1, ref)
    if ref == "refs/heads/main":
        return checkout.commit
    number = int(ref.split("/")[2])
    pull = api.json(f"/pulls/{number}")
    insist(type(pull.get("number")) is int and pull["number"] == number, "PR selector mismatch")
    head = object_record(pull.get("head"), "PR head metadata missing")
    base = object_record(pull.get("base"), "PR base metadata missing")
    repository(head.get("repo"))
    repository(base.get("repo"))
    insist(
        isinstance(base.get("ref"), str) and bool(base["ref"].strip()), "PR base branch is missing"
    )
    insist(
        pull.get("merge_commit_sha") == checkout.commit,
        "PR merge checkout changed before discovery",
    )
    value = head.get("sha")
    if not isinstance(value, str) or GIT_SHA.fullmatch(value) is None:
        raise GitHubEvidenceError("invalid PR head SHA")
    return value


def _matches(record: dict[str, Any], checkout: Checkout, ref: str, head: str) -> bool:
    event = "push" if ref == "refs/heads/main" else "pull_request"
    if (
        record.get("workflow_id") != WORKFLOW_ID
        or record.get("path") != WORKFLOW_PATH
        or record.get("head_sha") != head
        or record.get("event") != event
    ):
        return False
    if ref == "refs/heads/main":
        return record.get("head_branch") == "main"
    references = record.get("referenced_workflows")
    return isinstance(references, list) and any(
        isinstance(item, dict) and item.get("ref") == ref and item.get("sha") == checkout.commit
        for item in references
    )


def _completed(records: list[dict[str, Any]], ref: str) -> Selection | None:
    identifiers = [record.get("id") for record in records]
    insist(
        all(type(value) is int and value > 0 for value in identifiers),
        "invalid candidate CI run ID",
    )
    if not records:
        return None
    latest = max(records, key=lambda record: record["id"])
    if latest.get("status") != "completed":
        return None
    insist(
        latest.get("conclusion") == "success", "matching canonical CI run completed unsuccessfully"
    )
    attempt = latest.get("run_attempt")
    if type(attempt) is not int:
        raise GitHubEvidenceError("invalid candidate CI run attempt")
    return Selection(latest["id"], attempt, ref)


def wait_for_selection(root: Path, ref: str, timeout: int) -> Selection:
    insist(
        type(timeout) is int and 0 < timeout <= MAX_WAIT_SECONDS,
        "invalid hosted evidence wait budget",
    )
    checkout = capture_checkout(root)
    head = _head(GitHubTransport(), checkout, ref)
    event = "push" if ref == "refs/heads/main" else "pull_request"
    endpoint = f"/actions/workflows/{WORKFLOW_ID}/runs?event={event}&head_sha={head}"
    deadline = time.monotonic() + timeout
    for _poll in range(MAX_POLLS):
        # Each poll has one bounded request; the outer deadline and count bound the whole wait.
        records = GitHubTransport().collection(endpoint, "workflow_runs")
        selected = _completed([r for r in records if _matches(r, checkout, ref, head)], ref)
        if selected is not None:
            return selected
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(POLL_SECONDS, remaining))
    raise GitHubEvidenceError(
        "no successful same-checkout canonical CI run completed within the wait budget"
    )
