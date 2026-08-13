"""Release evidence must describe the evidence-bearing bytes shipped from Git HEAD."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from korpus.application.provenance import compute_source_digest
from scripts.source_digest import evidence_source_tree_digest, validate_evidence_source_binding


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(root),
            "GIT_AUTHOR_NAME": "KORPUS test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "KORPUS test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        },
    )


def _seed_repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    policy = root / "apps/api/src/korpus/policy.py"
    cache = root / "apps/api/src/korpus/__pycache__/policy.cpython-312.pyc"
    docs = root / "docs/README.md"
    policy.parent.mkdir(parents=True)
    cache.parent.mkdir(parents=True)
    docs.parent.mkdir(parents=True)
    policy.write_text("threshold = 1.0\n", encoding="utf-8")
    cache.write_bytes(b"generated-cache-must-not-bind")
    docs.write_text("first\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root, policy, docs


def test_committed_and_clean_live_evidence_use_one_digest(tmp_path: Path) -> None:
    root, _, _ = _seed_repository(tmp_path)
    live = compute_source_digest(root)
    committed = evidence_source_tree_digest(root=root)

    assert committed == live
    ok, failure, actual = validate_evidence_source_binding(live, root=root)
    assert (ok, failure, actual) == (True, None, committed)


def test_dirty_evidence_bearing_source_is_rejected_against_head(tmp_path: Path) -> None:
    root, policy, _ = _seed_repository(tmp_path)
    committed = evidence_source_tree_digest(root=root)

    policy.write_text("threshold = 0.0\n", encoding="utf-8")
    dirty = compute_source_digest(root)
    assert dirty != committed

    ok, failure, actual = validate_evidence_source_binding(dirty, root=root)
    assert ok is False
    assert failure == "assurance evidence source digest does not match committed HEAD"
    assert actual == committed


def test_documentation_only_edit_does_not_create_false_mismatch(tmp_path: Path) -> None:
    root, _, docs = _seed_repository(tmp_path)
    committed = evidence_source_tree_digest(root=root)

    docs.write_text("rewritten documentation only\n", encoding="utf-8")
    live = compute_source_digest(root)
    assert live == committed

    ok, failure, actual = validate_evidence_source_binding(live, root=root)
    assert (ok, failure, actual) == (True, None, committed)


@pytest.mark.parametrize("claimed", [None, "short", "z" * 64])
def test_missing_or_malformed_evidence_digest_fails_closed(
    tmp_path: Path, claimed: object
) -> None:
    root, _, _ = _seed_repository(tmp_path)

    ok, failure, actual = validate_evidence_source_binding(claimed, root=root)
    assert ok is False
    assert failure == "assurance evidence source digest is missing or malformed"
    assert actual == evidence_source_tree_digest(root=root)
