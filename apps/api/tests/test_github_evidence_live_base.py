"""A moving target branch has live authority separate from the PR's recorded base."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from github_evidence_run import Selection, admit_run  # noqa: E402

from .hosted_evidence_fixtures import (  # noqa: E402
    COMMIT,
    RUN_PATH,
    SELECTED,
    EvidenceFixture,
    encoded,
    measured_fixture,
    pull_request_fixture,
)

PR = Selection(SELECTED.run_id, SELECTED.attempt, "refs/pull/113/merge")
# The real base advance that exposed the mapping defect; other subjects remain neutral fixtures.
RECORDED_BASE = "087fbc7a1c55e03e5748fa2a4aee9d77f3cb81d4"
LIVE_BASE = "1ab2160de3ba7f5d642c0b37532542520c3a19a0"
BASE_PATH = "/git/ref/heads/main"
COMPARISON = f"/compare/{RECORDED_BASE}...{LIVE_BASE}"
COMPARE_PATH = COMPARISON + "?per_page=1&page=2"


def advanced_base_fixture(measured: EvidenceFixture) -> EvidenceFixture:
    fixture = pull_request_fixture(measured)
    fixture.replace_json("/pulls/113", lambda record: record["base"].update(sha=RECORDED_BASE))
    fixture.replace_json(
        f"/git/commits/{COMMIT}",
        lambda record: record.update(parents=[{"sha": LIVE_BASE}, {"sha": "c" * 40}]),
    )
    fixture.api.responses[BASE_PATH] = encoded(
        {"ref": "refs/heads/main", "object": {"type": "commit", "sha": LIVE_BASE}}
    )
    fixture.api.responses[COMPARE_PATH] = encoded(
        {
            "url": "https://api.github.com/repos/neuron7x/KORPUS" + COMPARISON,
            "base_commit": {"sha": RECORDED_BASE},
            "merge_base_commit": {"sha": RECORDED_BASE},
            "status": "ahead",
            "ahead_by": 3,
            "behind_by": 0,
            "total_commits": 3,
            # Page two intentionally is neither a full census nor the current tip.
            "commits": [{"sha": "e" * 40}],
        }
    )
    return fixture


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> EvidenceFixture:
    return measured_fixture(tmp_path_factory.mktemp("github-live-base"))


def test_current_base_merge_is_admitted_when_recorded_pr_base_is_an_ancestor(
    measured: EvidenceFixture,
) -> None:
    fixture = advanced_base_fixture(measured)
    run = admit_run(fixture.api, PR, fixture.checkout)
    assert run.checkout == fixture.checkout
    assert run.metadata["head_sha"] == "c" * 40
    assert fixture.api.json("/pulls/113")["base"]["sha"] == RECORDED_BASE != LIVE_BASE


def _replace(record: dict, path: tuple[str, ...], value) -> None:
    for key in path[:-1]:
        record = record[key]
    record[path[-1]] = value


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("ref",), "refs/heads/foreign"),
        (("ref",), "refs/tags/main"),
        (("ref",), None),
        (("object",), None),
        (("object", "type"), "tag"),
        (("object", "type"), None),
        (("object", "sha"), "not-a-commit"),
        (("object", "sha"), True),
        (("object", "sha"), None),
    ],
)
def test_live_base_requires_the_exact_named_commit_ref(
    measured: EvidenceFixture, path: tuple[str, ...], value
) -> None:
    fixture = advanced_base_fixture(measured)
    fixture.replace_json(BASE_PATH, lambda record: _replace(record, path, value))
    with pytest.raises(ValueError):
        admit_run(fixture.api, PR, fixture.checkout)


@pytest.mark.parametrize("value", [None, True, "", "d" * 39, "D" * 40])
def test_recorded_base_requires_a_full_lowercase_commit_sha(
    measured: EvidenceFixture, value
) -> None:
    fixture = advanced_base_fixture(measured)
    fixture.replace_json("/pulls/113", lambda record: record["base"].update(sha=value))
    with pytest.raises(ValueError, match="invalid recorded PR base SHA"):
        admit_run(fixture.api, PR, fixture.checkout)


@pytest.mark.parametrize("value", [None, True, [], "", "   "])
def test_base_branch_cannot_be_missing_or_coerced(measured: EvidenceFixture, value) -> None:
    fixture = advanced_base_fixture(measured)
    fixture.replace_json("/pulls/113", lambda record: record["base"].update(ref=value))
    with pytest.raises(ValueError, match="base branch is missing"):
        admit_run(fixture.api, PR, fixture.checkout)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("url",), "https://api.github.com/repos/foreign/repo" + COMPARISON),
        (("url",), "https://api.github.com/repos/neuron7x/KORPUS/compare/foreign...head"),
        (("url",), None),
        (("base_commit",), None),
        (("base_commit", "sha"), "f" * 40),
        (("merge_base_commit",), None),
        (("merge_base_commit", "sha"), "f" * 40),
        (("status",), "diverged"),
        (("status",), "behind"),
        (("status",), "identical"),
        (("ahead_by",), 0),
        (("ahead_by",), -1),
        (("ahead_by",), True),
        (("ahead_by",), 3.0),
        (("ahead_by",), "3"),
        (("behind_by",), 1),
        (("behind_by",), False),
        (("behind_by",), 0.0),
        (("behind_by",), "0"),
        (("total_commits",), 2),
        (("total_commits",), True),
        (("total_commits",), 3.0),
        (("total_commits",), None),
    ],
)
def test_base_ancestry_summary_requires_exact_sha_anchors_status_and_integer_counts(
    measured: EvidenceFixture, path: tuple[str, ...], value
) -> None:
    fixture = advanced_base_fixture(measured)
    fixture.replace_json(COMPARE_PATH, lambda record: _replace(record, path, value))
    with pytest.raises(ValueError):
        admit_run(fixture.api, PR, fixture.checkout)


def test_repointed_base_cannot_discard_the_recorded_pr_ancestor(
    measured: EvidenceFixture,
) -> None:
    fixture = advanced_base_fixture(measured)
    fixture.replace_json(
        COMPARE_PATH,
        lambda record: record.update(
            status="diverged", behind_by=2, merge_base_commit={"sha": "f" * 40}
        ),
    )
    with pytest.raises(ValueError, match="ancestor"):
        admit_run(fixture.api, PR, fixture.checkout)


def test_old_merge_cannot_pass_after_the_base_ref_advances(measured: EvidenceFixture) -> None:
    fixture = advanced_base_fixture(measured)
    fixture.replace_json(
        f"/git/commits/{COMMIT}",
        lambda record: record.update(parents=[{"sha": RECORDED_BASE}, {"sha": "c" * 40}]),
    )
    with pytest.raises(ValueError, match="exact PR base/head merge"):
        admit_run(fixture.api, PR, fixture.checkout)


def test_ancestry_metadata_does_not_require_a_complete_commit_census(
    measured: EvidenceFixture,
) -> None:
    fixture = advanced_base_fixture(measured)
    fixture.replace_json(
        COMPARE_PATH, lambda record: record.update(ahead_by=1000, total_commits=1000)
    )
    assert admit_run(fixture.api, PR, fixture.checkout).checkout == fixture.checkout


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("number",), 114),
        (("number",), 113.0),
        (("merge_commit_sha",), "f" * 40),
        (("head",), None),
        (("head", "sha"), "f" * 40),
        (("head", "ref"), "moved-head"),
        (("head", "repo", "id"), 123),
        (("head", "repo", "full_name"), "foreign/KORPUS"),
        (("head", "repo", "owner", "id"), 123),
        (("head", "repo", "owner", "login"), "foreign"),
        (("base",), None),
        (("base", "sha"), LIVE_BASE),
        (("base", "ref"), "retargeted-base"),
        (("base", "repo", "id"), 123),
        (("base", "repo", "full_name"), "foreign/KORPUS"),
        (("base", "repo", "owner", "id"), 123),
        (("base", "repo", "owner", "login"), "foreign"),
    ],
)
def test_final_pr_read_rejects_retargeting_or_movement_of_every_subject_edge(
    monkeypatch, measured: EvidenceFixture, path: tuple[str, ...], value
) -> None:
    fixture = advanced_base_fixture(measured)
    original = fixture.api.json
    reads = 0

    def reread(relative: str) -> dict:
        nonlocal reads
        record = original(relative)
        if relative == "/pulls/113":
            reads += 1
            if reads == 2:
                _replace(record, path, value)
        return record

    monkeypatch.setattr(fixture.api, "json", reread)
    with pytest.raises(ValueError):
        admit_run(fixture.api, PR, fixture.checkout)
    assert reads == 2


def test_final_base_read_rejects_a_ref_advance_during_admission(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = advanced_base_fixture(measured)
    original = fixture.api.json
    reads = 0

    def reread(relative: str) -> dict:
        nonlocal reads
        record = original(relative)
        if relative == BASE_PATH:
            reads += 1
            if reads == 2:
                record["object"]["sha"] = "f" * 40
        return record

    monkeypatch.setattr(fixture.api, "json", reread)
    with pytest.raises(ValueError, match="base ref changed during run admission"):
        admit_run(fixture.api, PR, fixture.checkout)
    assert reads == 2


def test_stability_rechecks_follow_the_job_census_before_artifact_capture(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = advanced_base_fixture(measured)
    original = fixture.api.json
    reads: list[str] = []

    def observe(relative: str) -> dict:
        reads.append(relative)
        return original(relative)

    monkeypatch.setattr(fixture.api, "json", observe)
    admit_run(fixture.api, PR, fixture.checkout)
    assert reads == [
        RUN_PATH,
        RUN_PATH + f"/attempts/{SELECTED.attempt}",
        f"/git/commits/{COMMIT}",
        "/pulls/113",
        BASE_PATH,
        COMPARE_PATH,
        RUN_PATH + f"/attempts/{SELECTED.attempt}/jobs?per_page=100",
        "/pulls/113",
        BASE_PATH,
    ]
    assert fixture.api.downloads == []
