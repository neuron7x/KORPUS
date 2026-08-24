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


def test_distribution_manifest_includes_untracked_package_artifacts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    package = tmp_path / "package"
    package.mkdir()
    (package / "source.txt").write_text("source", encoding="utf-8")
    (package / "evidence.json").write_text("{}", encoding="utf-8")
    (package / "DISTRIBUTION_MANIFEST.json").write_text("self", encoding="utf-8")

    manifest = module.build_manifest(package, kind="distribution")
    paths = [record["path"] for record in manifest["files"]]
    assert paths == ["evidence.json", "source.txt"]


def test_git_bundle_is_distribution_artifact_not_source(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    package = tmp_path / "package"
    package.mkdir()
    (package / "source.txt").write_text("source", encoding="utf-8")
    (package / "release.bundle").write_bytes(b"git-bundle")

    source_manifest = module.build_manifest(package, kind="source")
    distribution_manifest = module.build_manifest(package, kind="distribution")

    assert [record["path"] for record in source_manifest["files"]] == ["source.txt"]
    assert [record["path"] for record in distribution_manifest["files"]] == [
        "release.bundle",
        "source.txt",
    ]


def test_manifest_binds_posix_mode(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    repo = tmp_path / "repo"
    repo.mkdir()
    script = repo / "tool.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "tool.sh"], check=True)

    manifest = module.build_manifest(repo)

    assert manifest["schema"] == "korpus.source-manifest.v2"
    assert manifest["files"][0]["mode"] == "0755"


def test_manifest_root_changes_when_only_mode_changes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    repo = tmp_path / "repo"
    repo.mkdir()
    script = repo / "tool.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "tool.sh"], check=True)
    script.chmod(0o644)
    before = module.build_manifest(repo)["root_sha256"]
    script.chmod(0o755)
    after = module.build_manifest(repo)["root_sha256"]
    assert before != after


def test_distribution_manifest_excludes_only_its_root_self(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    package = tmp_path / "package"
    nested = package / "KORPUS_SOURCE"
    nested.mkdir(parents=True)
    (package / "DISTRIBUTION_MANIFEST.json").write_text("outer-self", encoding="utf-8")
    (nested / "DISTRIBUTION_MANIFEST.json").write_text("inner-bound", encoding="utf-8")

    manifest = module.build_manifest(package, kind="distribution")
    paths = [record["path"] for record in manifest["files"]]

    assert paths == ["KORPUS_SOURCE/DISTRIBUTION_MANIFEST.json"]
