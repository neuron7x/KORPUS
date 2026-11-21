"""The independent reader waits finitely and cannot substitute another CI source/event."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import github_evidence_wait as waiting  # noqa: E402
from github_evidence_run import Selection  # noqa: E402

from .hosted_evidence_fixtures import (  # noqa: E402
    COMMIT,
    RUN_PATH,
    SELECTED,
    EvidenceFixture,
    measured_fixture,
    pull_request_fixture,
)


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> EvidenceFixture:
    return measured_fixture(tmp_path_factory.mktemp("github-wait"))


def _clock(monkeypatch, measured: EvidenceFixture, batches: list[list[dict]]) -> list[float]:
    elapsed = [0.0]
    monkeypatch.setattr(waiting, "capture_checkout", lambda root: measured.checkout)
    monkeypatch.setattr(waiting.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        waiting.time, "sleep", lambda duration: elapsed.__setitem__(0, elapsed[0] + duration)
    )

    class API:
        def json(self, path):
            return measured.api.json(path)

        def collection(self, path, key):
            assert path.startswith(f"/actions/workflows/{waiting.WORKFLOW_ID}/runs?")
            assert key == "workflow_runs"
            return copy.deepcopy(batches.pop(0) if len(batches) > 1 else batches[0])

    monkeypatch.setattr(waiting, "GitHubTransport", API)
    return elapsed


def test_wait_requires_completed_success_and_uses_exact_latest_attempt(
    monkeypatch, measured: EvidenceFixture
) -> None:
    success = measured.api.json(RUN_PATH)
    pending = {**success, "status": "in_progress", "conclusion": None}
    elapsed = _clock(monkeypatch, measured, [[pending], [success]])
    assert waiting.wait_for_selection(measured.checkout.root, "refs/heads/main", 30) == SELECTED
    assert elapsed == [15]


def test_newer_pending_run_is_not_replaced_with_an_old_success(
    monkeypatch, measured: EvidenceFixture
) -> None:
    success = measured.api.json(RUN_PATH)
    pending = {**success, "id": success["id"] + 1, "status": "in_progress", "conclusion": None}
    elapsed = _clock(monkeypatch, measured, [[success, pending]])
    with pytest.raises(ValueError, match="wait budget"):
        waiting.wait_for_selection(measured.checkout.root, "refs/heads/main", 20)
    assert elapsed == [20]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("head_sha", "f" * 40),
        ("event", "workflow_dispatch"),
        ("workflow_id", 1),
        ("path", ".github/workflows/other.yml"),
        ("head_branch", "other"),
    ],
)
def test_wait_does_not_borrow_another_workflow_event_or_source(
    monkeypatch, measured: EvidenceFixture, field: str, value
) -> None:
    record = measured.api.json(RUN_PATH)
    record[field] = value
    _clock(monkeypatch, measured, [[record]])
    with pytest.raises(ValueError, match="wait budget"):
        waiting.wait_for_selection(measured.checkout.root, "refs/heads/main", 1)


def test_matching_failed_run_is_an_explicit_refusal(monkeypatch, measured: EvidenceFixture) -> None:
    record = measured.api.json(RUN_PATH)
    record["conclusion"] = "failure"
    elapsed = _clock(monkeypatch, measured, [[record]])
    with pytest.raises(ValueError, match="completed unsuccessfully"):
        waiting.wait_for_selection(measured.checkout.root, "refs/heads/main", 30)
    assert elapsed == [0]


def test_pr_wait_uses_api_head_and_exact_merge_checkout_reference(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = pull_request_fixture(measured)
    record = fixture.api.json(RUN_PATH)
    _clock(monkeypatch, fixture, [[record]])
    selected = waiting.wait_for_selection(fixture.checkout.root, "refs/pull/113/merge", 30)
    assert selected == Selection(SELECTED.run_id, SELECTED.attempt, "refs/pull/113/merge")
    assert record["head_sha"] != COMMIT


def test_pr_wait_refuses_current_pr_moved_away_from_checkout(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = pull_request_fixture(measured)
    fixture.replace_json("/pulls/113", lambda record: record.update(merge_commit_sha="f" * 40))
    _clock(monkeypatch, fixture, [[fixture.api.json(RUN_PATH)]])
    with pytest.raises(ValueError, match="merge checkout changed"):
        waiting.wait_for_selection(fixture.checkout.root, "refs/pull/113/merge", 30)


@pytest.mark.parametrize("budget", [0, -1, True, waiting.MAX_WAIT_SECONDS + 1])
def test_wait_cannot_be_made_unbounded(monkeypatch, measured: EvidenceFixture, budget: int) -> None:
    _clock(monkeypatch, measured, [[]])
    with pytest.raises(ValueError, match="wait budget"):
        waiting.wait_for_selection(measured.checkout.root, "refs/heads/main", budget)
