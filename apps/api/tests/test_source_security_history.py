"""Replay the pinned scanner's actual Git options against neutral merge history."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.source_security_commands import scanner_commands
from scripts.source_security_history_admission import require_complete_history_metadata

MERGE_ONLY = "NEUTRAL_TWO_PARENT_NOVEL_CONTENT"
REMOVED_SIDE = "NEUTRAL_SIDE_HISTORY_REMOVED_BEFORE_MERGE"
OCTOPUS_ONLY = "NEUTRAL_THREE_PARENT_NOVEL_CONTENT"
UNREACHABLE = "NEUTRAL_UNREACHABLE_BRANCH_CONTROL"


def _git(root: Path, *args: str) -> str:
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Neutral History Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Neutral History Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    }
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(root), *args],
        env=environment,
        check=True,
        timeout=10,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _commit(root: Path, path: str, content: str, message: str) -> str:
    (root / path).write_text(content + "\n", encoding="utf-8")
    _git(root, "add", "--", path)
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD").strip()


@dataclass(frozen=True)
class History:
    root: Path
    head: str
    merge: str
    reachable: frozenset[str]
    markers: frozenset[str]


@pytest.fixture(scope="module")
def history(tmp_path_factory: pytest.TempPathFactory) -> History:
    root = tmp_path_factory.mktemp("neutral-scanner-history")
    _git(root, "init", "--initial-branch=main")
    base = _commit(root, "base.txt", "NEUTRAL_BASE_CONTENT", "base")
    _git(root, "checkout", "-b", "side")
    _commit(root, "removed-side.txt", REMOVED_SIDE, "side addition")
    _git(root, "rm", "--", "removed-side.txt")
    _commit(root, "side.txt", "NEUTRAL_SIDE_TIP", "side removal")
    _git(root, "checkout", "main")
    _commit(root, "main.txt", "NEUTRAL_MAIN_TIP", "main advance")
    _git(root, "merge", "--no-ff", "--no-commit", "side")
    merge = _commit(root, "merge-only.txt", MERGE_ONLY, "merge with novel content")

    _git(root, "checkout", "-b", "octopus-a")
    _commit(root, "octopus-a.txt", "NEUTRAL_OCTOPUS_PARENT_A", "first side advance")
    _git(root, "checkout", "-b", "octopus-b", merge)
    _commit(root, "octopus-b.txt", "NEUTRAL_OCTOPUS_PARENT_B", "second side advance")
    _git(root, "checkout", "main")
    _commit(root, "main-later.txt", "NEUTRAL_MAIN_LATER", "main later advance")
    _git(root, "merge", "--no-ff", "--no-commit", "octopus-a", "octopus-b")
    head = _commit(root, "octopus-only.txt", OCTOPUS_ONLY, "octopus with novel content")

    _git(root, "checkout", "-b", "unreachable", base)
    _commit(root, "unreachable.txt", UNREACHABLE, "unreachable control")
    _git(root, "checkout", "main")
    markers = frozenset(
        {
            "NEUTRAL_BASE_CONTENT",
            REMOVED_SIDE,
            "NEUTRAL_SIDE_TIP",
            "NEUTRAL_MAIN_TIP",
            MERGE_ONLY,
            "NEUTRAL_OCTOPUS_PARENT_A",
            "NEUTRAL_OCTOPUS_PARENT_B",
            "NEUTRAL_MAIN_LATER",
            OCTOPUS_ONLY,
        }
    )
    return History(root, head, merge, frozenset(_git(root, "rev-list", head).split()), markers)


def _native_options(history: History) -> str:
    root = history.root
    command = scanner_commands(
        root, root, root / "output", root / "temporary", Path(sys.executable), history.head
    )["gitleaks"]
    assert command.count("--log-opts") == 1
    return command[command.index("--log-opts") + 1]


def _stream(history: History, options: str) -> str:
    # Pinned v8.30.1 sources/git.go appends strings.Split(logOpts, " ") to this prefix.
    return _git(history.root, "log", "-p", "-U0", *options.split(" "))


def _added_lines(stream: str) -> list[str]:
    """Read neutral additions from ordinary unified hunks, not combined merge syntax."""
    additions: list[str] = []
    patch = hunk = False
    for line in stream.splitlines():
        if line.startswith("commit "):
            patch = hunk = False
        elif line.startswith("diff --git "):
            patch, hunk = True, False
        elif line.startswith(("diff --cc ", "diff --combined ")):
            raise AssertionError("combined merge syntax is not an ordinary unified patch stream")
        elif patch and line.startswith("@@ "):
            hunk = True
        elif hunk and line.startswith("+") and not line.startswith("+++"):
            additions.append(line[1:])
    return additions


def _complete(history: History, stream: str) -> list[str]:
    commits = frozenset(re.findall(r"^commit ([0-9a-f]{40})\b", stream, re.MULTILINE))
    assert commits == history.reachable, "selected history lost a reachable commit"
    additions = _added_lines(stream)
    assert history.markers <= set(additions), "a historical text introduction was omitted"
    assert UNREACHABLE not in additions, "another branch expanded the selected revision"
    return additions


def test_actual_scanner_stream_includes_two_parent_merge_only_content(history: History) -> None:
    assert len(_git(history.root, "show", "-s", "--format=%P", history.merge).split()) == 2
    assert MERGE_ONLY in _added_lines(_stream(history, _native_options(history)))


def test_actual_scanner_stream_retains_side_content_removed_before_merge(history: History) -> None:
    assert "removed-side.txt" not in _git(
        history.root, "ls-tree", "-r", "--name-only", history.head
    )
    assert REMOVED_SIDE in _added_lines(_stream(history, _native_options(history)))


def test_actual_scanner_stream_includes_octopus_merge_only_content(history: History) -> None:
    assert len(_git(history.root, "show", "-s", "--format=%P", history.head).split()) == 3
    assert OCTOPUS_ONLY in _added_lines(_stream(history, _native_options(history)))


def test_actual_scanner_stream_keeps_every_reachable_commit_and_text_introduction(
    history: History,
) -> None:
    _complete(history, _stream(history, _native_options(history)))


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        " --full-history --first-parent --diff-merges=first-parent",
        " --full-history --diff-merges=combined",
        " --full-history --diff-merges=dense-combined",
    ],
    ids=["revision-only", "first-parent-traversal", "combined", "dense-combined"],
)
def test_neutral_fixture_refuses_incomplete_or_unsupported_streams(
    history: History, suffix: str
) -> None:
    with pytest.raises(AssertionError):
        _complete(history, _stream(history, history.head + suffix))


def test_first_parent_diff_mode_preserves_all_parent_traversal(history: History) -> None:
    options = history.head + " --full-history --diff-merges=first-parent"
    _complete(history, _stream(history, options))


def test_separate_parent_diffs_repeat_more_input_without_adding_marker_coverage(
    history: History,
) -> None:
    first = _stream(history, history.head + " --full-history --diff-merges=first-parent")
    separate = _stream(history, history.head + " --full-history --diff-merges=separate")
    first_added = _complete(history, first)
    separate_added = _complete(history, separate)
    assert len(separate_added) > len(first_added)
    assert len(separate.encode("utf-8")) > len(first.encode("utf-8"))


def test_scanner_command_disables_git_replace_refs(history: History) -> None:
    command = scanner_commands(
        history.root,
        history.root,
        history.root / "output",
        history.root / "temporary",
        Path(sys.executable),
        history.head,
    )["gitleaks"]
    assert command.count("GIT_NO_REPLACE_OBJECTS=1") == 1
    options = _native_options(history).split(" ")
    replacement = _git(history.root, "rev-parse", "unreachable").strip()
    try:
        _git(history.root, "replace", history.head, replacement)
        with pytest.raises(AssertionError):
            _complete(history, _stream(history, " ".join(options)))
        restored = subprocess.run(
            ["/usr/bin/git", "-C", str(history.root), "log", "-p", "-U0", *options],
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_NO_REPLACE_OBJECTS": "1",
            },
            capture_output=True,
            check=True,
            timeout=10,
            text=True,
        )
        _complete(history, restored.stdout)
    finally:
        _git(history.root, "replace", "-d", history.head)


@pytest.mark.parametrize("metadata", ("shallow", "info/grafts"))
def test_scanner_history_preflight_rejects_boundary_poison(history: History, metadata: str) -> None:
    require_complete_history_metadata(history.root)
    relative = Path(_git(history.root, "rev-parse", "--git-path", metadata).strip())
    path = history.root / relative
    assert not path.exists() and not path.is_symlink()
    try:
        path.write_text(history.head + "\n", encoding="ascii")
        # Ordinary Git traversal can terminate successfully after hiding ancestors.
        assert len(_git(history.root, "rev-list", history.head).splitlines()) == 1
        with pytest.raises(ValueError, match="shallow or"):
            require_complete_history_metadata(history.root)
    finally:
        path.unlink(missing_ok=True)
    require_complete_history_metadata(history.root)
