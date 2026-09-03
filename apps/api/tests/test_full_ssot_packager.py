from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.full_ssot_packager import included, project_files


def test_full_ssot_preserves_web_distribution_and_lineage() -> None:
    assert included(Path("apps/web/dist/index.html")) is True
    assert included(Path("LINEAGE/v0.8.1/ORIGINAL_CANONICAL_SNAPSHOT.zip")) is True


def test_full_ssot_excludes_only_runtime_or_secret_surfaces() -> None:
    assert included(Path("dist/local-build.zip")) is False
    assert included(Path("var/runtime.db")) is False
    assert included(Path("apps/api/__pycache__/x.pyc")) is False
    assert included(Path("infra/secrets/database_url.txt")) is False
    assert included(Path("apps/api/src/korpus/main.py")) is True


def test_full_ssot_admits_only_tracked_files_plus_the_built_web(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    tracked = root / "tracked.txt"
    tracked.write_text("source", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
    (root / ".coverage").write_text("host paths", encoding="utf-8")
    (root / ".env").write_text("secret", encoding="utf-8")
    (root / "untracked.txt").write_text("local", encoding="utf-8")
    web = root / "apps/web/dist/index.html"
    web.parent.mkdir(parents=True)
    web.write_text("built", encoding="utf-8")

    assert project_files(root) == [Path("apps/web/dist/index.html"), Path("tracked.txt")]


def test_deterministic_zip_roundtrip_preserves_executable_mode(tmp_path: Path) -> None:
    import stat

    from scripts.full_ssot_packager import _zip_tree
    from scripts.safe_archive_extract import extract_safe_archive

    stage = tmp_path / "artifact"
    script = stage / "scripts/run.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    archive = tmp_path / "artifact.zip"
    _zip_tree(stage, archive)
    extracted = extract_safe_archive(archive, tmp_path / "unpacked")
    assert stat.S_IMODE((extracted / "scripts/run.sh").stat().st_mode) == 0o755


def test_safe_extractor_refuses_unsafe_archive_before_write(tmp_path: Path) -> None:
    import zipfile

    import pytest

    from scripts.safe_archive_extract import extract_safe_archive

    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", b"blocked")
    destination = tmp_path / "unpacked"
    with pytest.raises(RuntimeError, match="unsafe release ZIP"):
        extract_safe_archive(archive, destination)
    assert not destination.exists() or not any(destination.rglob("*"))
