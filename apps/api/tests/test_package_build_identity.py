from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

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
                "version": "0.4.0",
                "tag": "v0.4.0",
                "artifact_stem": "KORPUS_SYSTEM_v0.4.0",
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
