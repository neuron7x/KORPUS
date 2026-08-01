from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


def _module(root: Path):
    script = root / "scripts" / "generate_manifest.py"
    spec = importlib.util.spec_from_file_location("generate_manifest", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_uses_only_git_tracked_files_in_worktree(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "tracked.txt").write_text("tracked", encoding="utf-8")
    (repo / "untracked.txt").write_text("untracked", encoding="utf-8")
    (repo / ".coverage").write_text("local", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)

    manifest = module.build_manifest(repo)
    paths = [record["path"] for record in manifest["files"]]
    assert paths == ["tracked.txt"]


def test_manifest_uses_archive_files_without_git(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "source.txt").write_text("source", encoding="utf-8")
    (archive / ".coverage").write_text("local", encoding="utf-8")

    manifest = module.build_manifest(archive)
    paths = [record["path"] for record in manifest["files"]]
    assert paths == ["source.txt"]
