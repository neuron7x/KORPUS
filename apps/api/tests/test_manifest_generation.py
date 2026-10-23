from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


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


def test_manifest_ignores_path_git_that_hides_tracked_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    repo, fake_bin = tmp_path / "repo", tmp_path / "fake-bin"
    repo.mkdir()
    fake_bin.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name in ("hidden.txt", "visible.txt"):
        (repo / name).write_text(name, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "hidden.txt", "visible.txt"], check=True)
    fake_git = fake_bin / "git"
    fake_git.write_text(
        '#!/bin/sh\ncase "$*" in\n*rev-parse*) printf "true\\n";;\n'
        '*ls-files*) printf "visible.txt\\0";;\nesac\n',
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))

    manifest = module.build_manifest(repo)

    assert [record["path"] for record in manifest["files"]] == ["hidden.txt", "visible.txt"]


def test_source_manifest_generator_refuses_tracked_symlink(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (repo / "linked.txt").symlink_to(outside)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "linked.txt"], check=True)

    with pytest.raises(ValueError, match="symlink"):
        module.build_manifest(repo)


def test_unavailable_trusted_git_falls_back_only_for_gitless_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    repo, snapshot = tmp_path / "repo", tmp_path / "snapshot"
    repo.mkdir()
    snapshot.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "source.txt").write_text("repository", encoding="utf-8")
    (snapshot / "source.txt").write_text("snapshot", encoding="utf-8")
    monkeypatch.setitem(module.source_paths.__globals__, "git_executable", lambda: None)

    with pytest.raises(RuntimeError, match="Git tree cannot be verified"):
        module.build_manifest(repo)
    assert [record["path"] for record in module.build_manifest(snapshot)["files"]] == ["source.txt"]


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


def test_git_bundle_is_source_eligible_and_digest_bound(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    package = tmp_path / "package"
    package.mkdir()
    (package / "source.txt").write_text("source", encoding="utf-8")
    (package / "release.bundle").write_bytes(b"git-bundle")

    source_manifest = module.build_manifest(package, kind="source")
    distribution_manifest = module.build_manifest(package, kind="distribution")

    assert [record["path"] for record in source_manifest["files"]] == [
        "release.bundle",
        "source.txt",
    ]
    assert [record["path"] for record in distribution_manifest["files"]] == [
        "release.bundle",
        "source.txt",
    ]
    original_root = source_manifest["root_sha256"]
    (package / "release.bundle").write_bytes(b"git-bundle-changed")
    assert module.build_manifest(package, kind="source")["root_sha256"] != original_root


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
