from __future__ import annotations

import importlib.util
import stat
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/deploy_public_web.py"
SPEC = importlib.util.spec_from_file_location("deploy_public_web", SCRIPT)
assert SPEC and SPEC.loader
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


def _build(path: Path) -> None:
    for name in deploy.REQUIRED:
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"content:{name}\n", encoding="utf-8")


def test_manifest_is_order_independent_and_content_addressed(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    _build(first)
    for source in sorted(first.iterdir(), reverse=True):
        second.mkdir(exist_ok=True)
        (second / source.name).write_bytes(source.read_bytes())
    assert deploy.artifact_manifest(first) == deploy.artifact_manifest(second)


def test_manifest_refuses_missing_required_asset_and_symlink(tmp_path: Path) -> None:
    _build(tmp_path)
    (tmp_path / "index.html").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        deploy.artifact_manifest(tmp_path)
    (tmp_path / "index.html").write_text("KORPUS", encoding="utf-8")
    (tmp_path / "escape").symlink_to(tmp_path / "index.html")
    with pytest.raises(ValueError, match="symlink"):
        deploy.artifact_manifest(tmp_path)


def test_staging_excludes_private_console_and_detects_tampering(tmp_path: Path) -> None:
    source, releases = tmp_path / "dist", tmp_path / "releases"
    _build(source)
    (source / "console.html").write_text("private", encoding="utf-8")
    release, _manifest = deploy.stage_release(source, releases)
    assert not (release / "console.html").exists()
    assert (release / "PUBLIC_MANIFEST.json").is_file()
    assert stat.S_IMODE(release.stat().st_mode) == 0o755
    assert stat.S_IMODE((release / "index.html").stat().st_mode) == 0o644
    assert deploy.stage_release(source, releases)[0] == release
    (release / "app.js").write_text("tampered", encoding="utf-8")
    with pytest.raises(RuntimeError, match="modified"):
        deploy.stage_release(source, releases)
