"""A PR's API head is not its actual merge checkout; every connecting edge is checked."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from github_coverage_admission import verified_coverage  # noqa: E402
from github_evidence_artifact import admit_artifact, artifact_inventory  # noqa: E402
from github_evidence_result import result  # noqa: E402
from github_evidence_run import POSTGRES, SQLITE, Selection, admit_run  # noqa: E402

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


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> EvidenceFixture:
    return pull_request_fixture(measured_fixture(tmp_path_factory.mktemp("github-pr-merge")))


def test_pr_head_and_native_merge_checkout_remain_distinct_valid_subjects(
    measured: EvidenceFixture,
) -> None:
    fixture = measured.clone()
    run = admit_run(fixture.api, PR, fixture.checkout)
    inventory = artifact_inventory(fixture.api, run)
    sqlite = admit_artifact(fixture.api, run, SQLITE, inventory)
    postgres = admit_artifact(fixture.api, run, POSTGRES, inventory)
    coverage = verified_coverage(run, sqlite, postgres)
    evidence = result(run, coverage, (sqlite, postgres))
    assert evidence.identity.head_sha == "c" * 40
    assert evidence.identity.checkout_commit_sha == COMMIT
    assert evidence.identity.ref == "refs/pull/113/merge"
    assert run.receipt_run["GITHUB_SHA"] == COMMIT != run.metadata["head_sha"]
    assert coverage["totals"]["percent_covered"] == 100


@pytest.mark.parametrize("base_ref", ["issue-105-package-contract", "feature/stacked"])
def test_stacked_pr_base_is_bound_by_actual_parent_commit_not_a_branch_name(
    measured: EvidenceFixture,
    base_ref: str,
) -> None:
    fixture = measured.clone()
    fixture.replace_json("/pulls/113", lambda record: record["base"].update(ref=base_ref))
    fixture.api.responses[f"/git/ref/heads/{base_ref}"] = encoded(
        {"ref": f"refs/heads/{base_ref}", "object": {"type": "commit", "sha": "d" * 40}}
    )
    run = admit_run(fixture.api, PR, fixture.checkout)
    assert run.checkout.commit == COMMIT and run.metadata["head_sha"] == "c" * 40


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("number",), 114),
        (("merge_commit_sha",), "f" * 40),
        (("head", "sha"), "f" * 40),
        (("head", "ref"), "foreign"),
        (("base", "sha"), "f" * 40),
        (("base", "ref"), ""),
        (("head", "repo", "id"), 999),
        (("base", "repo", "owner", "id"), 999),
    ],
)
def test_pr_mapping_rejects_foreign_or_stale_api_edges(
    measured: EvidenceFixture, path: tuple, value
) -> None:
    fixture = measured.clone()
    pull = fixture.api.json("/pulls/113")
    current = pull
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    fixture.api.responses["/pulls/113"] = encoded(pull)
    with pytest.raises(ValueError):
        admit_run(fixture.api, PR, fixture.checkout)


@pytest.mark.parametrize(
    "parents", [[], [{"sha": "c" * 40}], [{"sha": "c" * 40}, {"sha": "d" * 40}]]
)
def test_same_tree_does_not_substitute_for_exact_pr_merge_parents(
    measured: EvidenceFixture, parents: list
) -> None:
    fixture = measured.clone()
    fixture.replace_json(f"/git/commits/{COMMIT}", lambda record: record.update(parents=parents))
    with pytest.raises(ValueError, match="exact PR base/head merge"):
        admit_run(fixture.api, PR, fixture.checkout)


@pytest.mark.parametrize(
    ("field", "value"),
    [("sha", "f" * 40), ("ref", "refs/pull/114/merge"), ("path", "foreign/workflow")],
)
def test_run_must_prove_the_actual_checkout_ref_and_reusable_workflow(
    measured: EvidenceFixture, field: str, value: str
) -> None:
    fixture = measured.clone()
    endpoint = RUN_PATH + f"/attempts/{SELECTED.attempt}"
    record = fixture.api.json(endpoint)
    record["referenced_workflows"][0][field] = value
    fixture.api.responses[endpoint] = encoded(record)
    with pytest.raises(ValueError, match="selected PR merge checkout/ref"):
        admit_run(fixture.api, PR, fixture.checkout)


def test_native_receipt_cannot_substitute_pr_head_for_executed_merge(
    measured: EvidenceFixture,
) -> None:
    fixture = measured.clone()
    name = "coverage-sqlite-receipt.json"
    receipt = json.loads(fixture.members[SQLITE.job][name])
    receipt["run"]["GITHUB_SHA"] = "c" * 40
    fixture.members[SQLITE.job][name] = encoded(receipt)
    fixture.repack(SQLITE)
    run = admit_run(fixture.api, PR, fixture.checkout)
    inventory = artifact_inventory(fixture.api, run)
    sqlite = admit_artifact(fixture.api, run, SQLITE, inventory)
    postgres = admit_artifact(fixture.api, run, POSTGRES, inventory)
    with pytest.raises(ValueError, match="another repository/SHA/run/attempt"):
        verified_coverage(run, sqlite, postgres)
