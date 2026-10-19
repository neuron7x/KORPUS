from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from korpus.application.release_claim_tree import tracked_tree_digest


def _commit(root: Path, value: str) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "source.py").write_text(value, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "source.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=KORPUS test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )


def test_digest_ignores_git_repository_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _commit(first, "first = True\n")
    _commit(second, "second = True\n")
    expected = tracked_tree_digest(first)
    redirected = tracked_tree_digest(second)
    assert expected is not None and redirected is not None and expected != redirected

    monkeypatch.setenv("GIT_DIR", str(second / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(second))
    monkeypatch.setenv("GIT_INDEX_FILE", str(second / ".git/index"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(second / ".git/objects"))
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", str(second / ".git/objects"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.worktree")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(second))
    assert tracked_tree_digest(first) == expected


def test_digest_overrides_local_core_worktree(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _commit(first, "first = True\n")
    _commit(second, "second = True\n")
    expected = tracked_tree_digest(first)
    subprocess.run(["git", "-C", str(first), "config", "core.worktree", str(second)], check=True)
    assert tracked_tree_digest(first) == expected


def test_digest_refuses_assume_unchanged_dirty_bytes(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _commit(repository, "answer = 1\n")
    assert tracked_tree_digest(repository) is not None
    subprocess.run(
        ["git", "-C", str(repository), "update-index", "--assume-unchanged", "source.py"],
        check=True,
    )
    (repository / "source.py").write_text("answer = 2\n", encoding="utf-8")
    assert tracked_tree_digest(repository) is None


def test_digest_refuses_untracked_source_even_when_ignored(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _commit(repository, "answer = 1\n")
    (repository / ".gitignore").write_text("hidden.py\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", ".gitignore"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=KORPUS test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "ignore declaration",
        ],
        check=True,
    )
    (repository / "hidden.py").write_text("hidden = True\n", encoding="utf-8")
    assert tracked_tree_digest(repository) is None


def test_git_environment_does_not_leak_back_to_process(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _commit(repository, "answer = 1\n")
    before = dict(os.environ)
    assert tracked_tree_digest(repository) is not None
    assert dict(os.environ) == before


def test_digest_refuses_worktree_mode_drift(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _commit(repository, "answer = 1\n")
    assert tracked_tree_digest(repository) is not None
    (repository / "source.py").chmod(0o755)
    assert tracked_tree_digest(repository) is None


def test_digest_refuses_missing_tracked_source(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _commit(repository, "answer = 1\n")
    assert tracked_tree_digest(repository) is not None
    (repository / "source.py").unlink()
    assert tracked_tree_digest(repository) is None
