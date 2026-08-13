"""Release evidence must describe the evidence-bearing bytes shipped from Git HEAD."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from korpus.application.provenance import compute_source_digest
from scripts.evidence_source_binding import (
    committed_evidence_source_digest,
    evidence_source_binding_failure,
)


def _git(root: Path, *args: str) -> None:
    env = {
        **os.environ,
        "HOME": str(root),
        "GIT_AUTHOR_NAME": "KORPUS test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "KORPUS test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=env)


def _seed_repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    policy = root / "apps/api/src/korpus/policy.py"
    cache = root / "apps/api/src/korpus/__pycache__/policy.cpython-312.pyc"
    docs = root / "docs/README.md"
    makefile = root / "Makefile"
    workflow = root / ".github/workflows/assurance.yml"
    policy.parent.mkdir(parents=True)
    cache.parent.mkdir(parents=True)
    docs.parent.mkdir(parents=True)
    workflow.parent.mkdir(parents=True)
    policy.write_text("threshold = 1.0\n", encoding="utf-8")
    cache.write_bytes(b"generated-cache-must-not-bind")
    docs.write_text("first\n", encoding="utf-8")
    makefile.write_text("mutation:\n\tpython scripts/run_mutation.py\n", encoding="utf-8")
    workflow.write_text("jobs:\n  assurance:\n    runs-on: ubuntu-24.04\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root, policy, docs


def test_committed_and_clean_live_evidence_use_one_digest(tmp_path: Path) -> None:
    root, _, _ = _seed_repository(tmp_path)
    live = compute_source_digest(root)
    committed = committed_evidence_source_digest(root=root)

    assert committed == live
    assert evidence_source_binding_failure(live, root=root) is None


def test_dirty_evidence_bearing_source_is_rejected_against_head(tmp_path: Path) -> None:
    root, policy, _ = _seed_repository(tmp_path)
    committed = committed_evidence_source_digest(root=root)

    policy.write_text("threshold = 0.0\n", encoding="utf-8")
    dirty = compute_source_digest(root)
    assert dirty != committed
    assert (
        evidence_source_binding_failure(dirty, root=root)
        == "assurance evidence source digest does not match committed HEAD"
    )


def test_untracked_evidence_bearing_source_is_rejected_against_head(tmp_path: Path) -> None:
    root, policy, _ = _seed_repository(tmp_path)
    committed = committed_evidence_source_digest(root=root)
    extra = policy.with_name("untracked_policy.py")

    extra.write_text("threshold = 0.5\n", encoding="utf-8")
    dirty = compute_source_digest(root)
    assert dirty != committed
    assert (
        evidence_source_binding_failure(dirty, root=root)
        == "assurance evidence source digest does not match committed HEAD"
    )


def test_deleted_evidence_bearing_source_is_rejected_against_head(tmp_path: Path) -> None:
    root, policy, _ = _seed_repository(tmp_path)
    committed = committed_evidence_source_digest(root=root)

    policy.unlink()
    dirty = compute_source_digest(root)
    assert dirty != committed
    assert (
        evidence_source_binding_failure(dirty, root=root)
        == "assurance evidence source digest does not match committed HEAD"
    )


def test_makefile_assurance_orchestration_edit_changes_digest(tmp_path: Path) -> None:
    root, _, _ = _seed_repository(tmp_path)
    committed = committed_evidence_source_digest(root=root)

    (root / "Makefile").write_text(
        "mutation:\n\tKORPUS_MUTATION_SHARDS=1 python scripts/run_mutation.py\n",
        encoding="utf-8",
    )
    assert compute_source_digest(root) != committed


def test_assurance_workflow_edit_changes_digest(tmp_path: Path) -> None:
    root, _, _ = _seed_repository(tmp_path)
    committed = committed_evidence_source_digest(root=root)

    (root / ".github/workflows/assurance.yml").write_text(
        "jobs:\n  assurance:\n    runs-on: ubuntu-22.04\n",
        encoding="utf-8",
    )
    assert compute_source_digest(root) != committed


def test_documentation_only_edit_does_not_create_false_mismatch(tmp_path: Path) -> None:
    root, _, docs = _seed_repository(tmp_path)
    committed = committed_evidence_source_digest(root=root)

    docs.write_text("rewritten documentation only\n", encoding="utf-8")
    live = compute_source_digest(root)
    assert live == committed
    assert evidence_source_binding_failure(live, root=root) is None


def test_unverifiable_git_ref_fails_closed(tmp_path: Path) -> None:
    root, _, _ = _seed_repository(tmp_path)
    live = compute_source_digest(root)
    assert (
        evidence_source_binding_failure(live, ref="missing-release-ref", root=root)
        == "assurance evidence source digest cannot be verified against committed HEAD"
    )


@pytest.mark.parametrize("claimed", [None, "short", "z" * 64])
def test_missing_or_malformed_evidence_digest_fails_closed(
    tmp_path: Path, claimed: object
) -> None:
    root, _, _ = _seed_repository(tmp_path)
    assert (
        evidence_source_binding_failure(claimed, root=root)
        == "assurance evidence source digest is missing or malformed"
    )
