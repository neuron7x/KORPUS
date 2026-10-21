from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_package_build_identity.py"


def _module():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("verify_package_build_identity", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "pkg"
    release = root / "apps/api/src/korpus/release.json"
    release.parent.mkdir(parents=True)
    release.write_text(
        json.dumps(
            {
                "schema": "korpus.release-identity.v1",
                "product": "KORPUS",
                "version": "0.4.0",
                "tag": "v0.4.0",
                "artifact_stem": "KORPUS_SYSTEM_v0.4.0",
                "distribution_artifact": "KORPUS_SYSTEM_v0.4.0.zip",
            }
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(b"source").hexdigest()
    (root / "SOURCE_MANIFEST.json").write_text(
        json.dumps({"schema": "korpus.source-manifest.v2", "root_sha256": digest}),
        encoding="utf-8",
    )
    (root / "PACKAGE_BUILD.json").write_text(
        json.dumps(
            {
                "schema": "korpus.package-build.v2",
                "release": "v0.4.0",
                "derived_from_source_commit": "a" * 40,
                "source_commit": None,
                "source_manifest_root_sha256": digest,
                "history_included": False,
                "import_required_to_obtain_git_commit": True,
            }
        ),
        encoding="utf-8",
    )
    return root


def test_clean_source_package_build_identity_passes(tmp_path: Path) -> None:
    module = _module()
    assert module.verify(_fixture(tmp_path)) == []


def test_stale_source_manifest_binding_is_rejected(tmp_path: Path) -> None:
    module = _module()
    root = _fixture(tmp_path)
    build = json.loads((root / "PACKAGE_BUILD.json").read_text(encoding="utf-8"))
    build["source_manifest_root_sha256"] = "b" * 64
    (root / "PACKAGE_BUILD.json").write_text(json.dumps(build), encoding="utf-8")
    assert "package build source manifest root mismatch" in module.verify(root)


def test_gitless_package_cannot_claim_an_invented_commit(tmp_path: Path) -> None:
    module = _module()
    root = _fixture(tmp_path)
    build = json.loads((root / "PACKAGE_BUILD.json").read_text(encoding="utf-8"))
    build["source_commit"] = "c" * 40
    (root / "PACKAGE_BUILD.json").write_text(json.dumps(build), encoding="utf-8")
    assert "gitless canonical package must not invent a source commit" in module.verify(root)


IDENTITY_PATHS = (
    "PACKAGE_BUILD.json",
    "SOURCE_MANIFEST.json",
    "apps/api/src/korpus/release.json",
)


@pytest.mark.parametrize("relative", IDENTITY_PATHS)
def test_identity_file_symlink_is_rejected(tmp_path: Path, relative: str) -> None:
    module = _module()
    root = _fixture(tmp_path)
    path = root / relative
    target = path.with_name(f"{path.name}.target")
    path.rename(target)
    path.symlink_to(target.name)
    assert "missing or symlinked" in module.verify(root)[0]


def test_identity_parent_symlink_is_rejected(tmp_path: Path) -> None:
    module = _module()
    root = _fixture(tmp_path)
    alias = tmp_path / "pkg-alias"
    alias.symlink_to(root, target_is_directory=True)
    assert "missing or symlinked" in module.verify(alias)[0]


def _append_raw(root: Path, relative: str, field: str) -> None:
    path = root / relative
    payload = path.read_text(encoding="utf-8")
    path.write_text(f"{payload[:-1]}, {field}}}", encoding="utf-8")


@pytest.mark.parametrize("relative", IDENTITY_PATHS)
def test_duplicate_identity_key_is_rejected(tmp_path: Path, relative: str) -> None:
    module = _module()
    root = _fixture(tmp_path)
    _append_raw(root, relative, '"schema": "duplicate"')
    assert "duplicate key" in module.verify(root)[0]


@pytest.mark.parametrize("relative", IDENTITY_PATHS)
def test_nonfinite_identity_value_is_rejected(tmp_path: Path, relative: str) -> None:
    module = _module()
    root = _fixture(tmp_path)
    _append_raw(root, relative, '"nonfinite": NaN')
    assert "non-finite constant" in module.verify(root)[0]


@pytest.mark.parametrize("field", ("source_commit", "derived_from_source_commit"))
def test_nullable_package_build_fields_must_be_explicit(tmp_path: Path, field: str) -> None:
    module = _module()
    root = _fixture(tmp_path)
    build_path = root / "PACKAGE_BUILD.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    del build[field]
    build_path.write_text(json.dumps(build), encoding="utf-8")
    assert "package build fields mismatch" in module.verify(root)


def test_unexpected_package_build_field_is_rejected(tmp_path: Path) -> None:
    module = _module()
    root = _fixture(tmp_path)
    build_path = root / "PACKAGE_BUILD.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    build["unexpected"] = None
    build_path.write_text(json.dumps(build), encoding="utf-8")
    assert "package build fields mismatch" in module.verify(root)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema", "wrong.schema"),
        ("product", "OTHER"),
        ("artifact_stem", 1),
        ("distribution_artifact", "wrong.zip"),
    ),
)
def test_release_identity_contract_is_exact(tmp_path: Path, field: str, value: object) -> None:
    module = _module()
    root = _fixture(tmp_path)
    release_path = root / "apps/api/src/korpus/release.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release[field] = value
    release_path.write_text(json.dumps(release), encoding="utf-8")
    assert "release identity contract mismatch" in module.verify(root)


def test_release_identity_fields_are_exact(tmp_path: Path) -> None:
    module = _module()
    root = _fixture(tmp_path)
    release_path = root / "apps/api/src/korpus/release.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["unexpected"] = None
    release_path.write_text(json.dumps(release), encoding="utf-8")
    assert "release identity contract mismatch" in module.verify(root)
