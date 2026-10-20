"""Adversarial Git environment must not redirect canonical source digest queries."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import source_digest


def _commit(root: Path, value: str) -> str:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    target = root / "scripts/source.py"
    target.parent.mkdir()
    target.write_text(value, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "scripts/source.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=KORPUS adversarial test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_tracked_source_digest_ignores_hostile_git_repository_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local, foreign = tmp_path / "local", tmp_path / "foreign"
    _commit(local, "local = 1\n")
    _commit(foreign, "foreign = 2\n")
    monkeypatch.setattr(source_digest, "ROOT", local)
    expected = source_digest.source_tree_digest()
    monkeypatch.setattr(source_digest, "ROOT", foreign)
    foreign_digest = source_digest.source_tree_digest()
    assert expected != foreign_digest

    monkeypatch.setattr(source_digest, "ROOT", local)
    poison = {
        "GIT_DIR": str(foreign / ".git"),
        "GIT_WORK_TREE": str(foreign),
        "GIT_INDEX_FILE": str(foreign / ".git/index"),
        "GIT_OBJECT_DIRECTORY": str(foreign / ".git/objects"),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(foreign / ".git/objects"),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.worktree",
        "GIT_CONFIG_VALUE_0": str(foreign),
    }
    for key, value in poison.items():
        monkeypatch.setenv(key, value)

    assert source_digest.source_tree_digest() == expected
    assert source_digest._git("show", "HEAD:scripts/source.py") == b"local = 1\n"


def test_source_digest_refuses_untrusted_git_instead_of_relaxing_to_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _commit(tmp_path / "repo", "local = 1\n")
    monkeypatch.setattr(source_digest, "ROOT", tmp_path / "repo")
    monkeypatch.setattr(source_digest, "git_executable", lambda: None)
    with pytest.raises(RuntimeError, match="git metadata"):
        source_digest.source_tree_digest()


def test_evidence_source_history_comparison_ignores_foreign_git_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local, foreign = tmp_path / "local", tmp_path / "foreign"
    parent = _commit(local, "source = 1\n")
    _commit(foreign, "source = 1\n")
    (local / "scripts/source.py").write_text("source = 2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(local), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(local),
            "-c",
            "user.name=KORPUS adversarial test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "second fixture",
        ],
        check=True,
    )
    head = subprocess.run(
        ["git", "-C", str(local), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    monkeypatch.setattr(source_digest, "ROOT", local)
    assert source_digest._same_evidence_source(parent, head) is False
    monkeypatch.setenv("GIT_DIR", str(foreign / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(foreign))
    assert source_digest._same_evidence_source(parent, head) is False
    assert source_digest.commits_with_identical_source("HEAD")[0] == head
