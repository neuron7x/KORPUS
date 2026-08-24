"""The three walk-based checks, shown detecting.

`repo.no_plaintext_secrets`, `repo.no_oversized_files` and
`repo.no_unresolved_placeholders` all pass on the shipped tree, which is the state they
are meant to hold — and which means asserting over the shipped tree alone proves
nothing about whether they can detect anything. A detector that always returns an empty
list satisfies all three.

The same shape let M145 survive earlier today: "the register has no duplicate ids" is
satisfied by a duplicate-finder that finds nothing. So each is exercised against a tree
built to violate it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from korpus.repository_requirements import load_context


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "infra/secrets").mkdir(parents=True)
    (tmp_path / "apps/api/src/korpus").mkdir(parents=True)
    return tmp_path


def test_a_clean_tree_reports_nothing(tmp_path: Path) -> None:
    """The dual: a walk that always reports problems is as useless as one that never does."""
    context = load_context(_tree(tmp_path))

    assert context.oversized == []
    assert context.placeholders == []
    assert context.tracked_secrets == []


def test_a_plaintext_secret_in_the_tree_is_detected(tmp_path: Path) -> None:
    """A secret in the tree is disclosed to everyone who ever clones it, forever."""
    root = _tree(tmp_path)
    (root / "infra/secrets/postgres_password.txt").write_text("hunter2", encoding="utf-8")

    assert load_context(root).tracked_secrets == ["infra/secrets/postgres_password.txt"]


def test_a_secret_outside_the_secrets_directory_is_not_flagged(tmp_path: Path) -> None:
    """Scoped deliberately: flagging every .txt would make the check unreadable."""
    root = _tree(tmp_path)
    (root / "README.txt").write_text("not a secret", encoding="utf-8")

    assert load_context(root).tracked_secrets == []


def test_an_oversized_file_is_detected(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "corpus-dump.bin").write_bytes(b"x" * 5_000_001)

    assert load_context(root).oversized == ["corpus-dump.bin"]


def test_a_file_at_the_limit_is_not_flagged(tmp_path: Path) -> None:
    """Off-by-one here rejects a legitimate artefact at exactly the boundary."""
    root = _tree(tmp_path)
    (root / "at-the-limit.bin").write_bytes(b"x" * 5_000_000)

    assert load_context(root).oversized == []


def test_an_unresolved_placeholder_is_detected(tmp_path: Path) -> None:
    """NotImplementedError in a delivered path is a promise the runtime cannot keep."""
    root = _tree(tmp_path)
    # Assembled rather than written literally: the detector scans every .py in the
    # tree, so spelling the pattern here would make this test file trip the check it
    # is testing — which it did on the first run.
    placeholder = "raise " + "NotImplementedError"
    (root / "apps/api/src/korpus/half_done.py").write_text(
        f"def answer():\n    {placeholder}\n", encoding="utf-8"
    )

    assert load_context(root).placeholders == ["apps/api/src/korpus/half_done.py"]


def test_a_todo_implement_comment_is_detected(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    marker = "TODO" + ": implement"
    (root / "notes.md").write_text(f"# {marker} the reviewer flow\n", encoding="utf-8")

    assert load_context(root).placeholders == ["notes.md"]


def test_ignored_directories_are_not_walked(tmp_path: Path) -> None:
    """CI sets PIP_CACHE_DIR inside the checkout: the first locked-environment pipeline
    reported five pip wheels as oversized repository files."""
    root = _tree(tmp_path)
    (root / ".cache/pip").mkdir(parents=True)
    (root / ".cache/pip/wheel.whl").write_bytes(b"x" * 5_000_001)

    assert load_context(root).oversized == []


def test_an_unparseable_contract_is_recorded(tmp_path: Path) -> None:
    """A contract that does not parse is a contract nothing enforces."""
    root = _tree(tmp_path)
    (root / "contracts").mkdir()
    (root / "contracts/openapi.json").write_text("{ not json", encoding="utf-8")

    assert any("openapi.json" in problem for problem in load_context(root).invalid_json)


def test_a_secret_git_ignores_is_not_reported_as_tracked(tmp_path: Path) -> None:
    """`make infra-secrets` writes eight key files that git never sees.

    The requirement is named `tracked_secrets` and measured presence on disk, so
    following the repository's own documented setup step made `make validate` fail on
    files `infra/secrets/.gitignore` explicitly excludes. A developer broke the
    validator by following the README (2026-08-06).
    """
    root = _tree(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "infra/secrets/.gitignore").write_text("*.txt\n", encoding="utf-8")
    (root / "infra/secrets/postgres_password.txt").write_text("hunter2", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)

    assert load_context(root).tracked_secrets == []


def test_a_secret_git_does_track_is_still_reported(tmp_path: Path) -> None:
    """The dual. Without it the check above is satisfied by never reporting anything."""
    root = _tree(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "infra/secrets/postgres_password.txt").write_text("hunter2", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", "infra/secrets/postgres_password.txt"], cwd=root, check=True
    )

    assert load_context(root).tracked_secrets == ["infra/secrets/postgres_password.txt"]


def test_full_ssot_allows_only_oversized_lineage_archive(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "LINEAGE").mkdir()
    (root / "LINEAGE/archive.zip").write_bytes(b"x" * 5_000_001)
    assert load_context(root, "SOURCE_CHECKOUT").oversized == ["LINEAGE/archive.zip"]
    assert load_context(root, "FULL_SSOT_DISTRIBUTION").oversized == []
    (root / "payload.bin").write_bytes(b"x" * 5_000_001)
    assert load_context(root, "FULL_SSOT_DISTRIBUTION").oversized == ["payload.bin"]
