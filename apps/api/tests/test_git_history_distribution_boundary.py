"""Distribution must never make confidentiality depend on repository lifetime history."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MARKER = "KORPUS-DELETED-HISTORY-CONTROL-7F91A8"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_deleted_blob_remains_recoverable_from_all_refs_git_bundle(tmp_path: Path) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.name", "KORPUS boundary control")
    _git(repository, "config", "user.email", "boundary-control@example.invalid")

    secret = repository / "secret-marker.txt"
    secret.write_text(MARKER + "\n", encoding="utf-8")
    _git(repository, "add", "secret-marker.txt")
    _git(repository, "commit", "-m", "control: add historical marker")
    marker_commit = _git(repository, "rev-parse", "HEAD")

    secret.unlink()
    _git(repository, "add", "-u")
    _git(repository, "commit", "-m", "control: delete historical marker")
    assert not secret.exists()

    bundle = tmp_path / "history.bundle"
    _git(repository, "bundle", "create", str(bundle), "--all")
    recovered = tmp_path / "recovered"
    subprocess.run(
        ["git", "clone", "--quiet", str(bundle), str(recovered)],
        check=True,
        capture_output=True,
        text=True,
    )

    historical = _git(recovered, "show", f"{marker_commit}:secret-marker.txt")
    assert historical == MARKER


def test_package_producer_excludes_git_history_by_construction() -> None:
    producer = (ROOT / "scripts/package_repository.sh").read_text(encoding="utf-8")

    assert "git bundle" not in producer
    assert "git archive --format=tar HEAD" in producer
    assert "Git history, branches, refs та deleted historical blobs" in producer
