from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from scripts.manifest_lib.integrity import file_record, manifest_root

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_source_manifest.py"
SPEC = importlib.util.spec_from_file_location("verify_source_manifest", SCRIPT)
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def test_invalid_manifest_never_emits_a_supported_report(tmp_path: Path) -> None:
    release = tmp_path / "apps/api/src/korpus/release.json"
    release.parent.mkdir(parents=True)
    release.write_text(
        '{"schema":"x","product":"x","version":"9","tag":"v9",'
        '"artifact_stem":"x","distribution_artifact":"x.zip"}',
        encoding="utf-8",
    )
    report = VERIFY.bound_report(tmp_path)
    assert report["status"] == "FAIL"


def test_evidence_refresh_verifies_the_manifest_before_rendering_claims() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("evidence-refresh:", 1)[1].split("\n\n", 1)[0]
    ordered = (
        "generate_manifest.py",
        "verify_source_manifest.py --out reports/SOURCE_MANIFEST_VERIFICATION_CURRENT.json",
        "release-truth",
        "current-truth-verify",
    )
    positions = [recipe.index(item) for item in ordered]
    assert positions == sorted(positions)


def _write_manifest(root: Path, records: list[dict[str, object]]) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema": "korpus.source-manifest.v2",
        "kind": "source",
        "manifest_self_excluded": True,
        "file_count": len(records),
        "root_sha256": manifest_root(records),
        "files": records,
    }
    (root / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _fixture(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "source.py"
    source.write_text("x", encoding="utf-8")
    record = file_record(source, Path("source.py"), source=True)
    return _write_manifest(tmp_path, [record])


def test_canonical_gitless_source_manifest_passes(tmp_path: Path) -> None:
    _fixture(tmp_path)
    assert VERIFY.verify(tmp_path)["valid"] is True


def test_source_manifest_file_symlink_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    root.mkdir()
    _fixture(root)
    manifest, outside = root / "SOURCE_MANIFEST.json", tmp_path / "outside-manifest.json"
    manifest.replace(outside)
    manifest.symlink_to(outside)

    assert VERIFY.verify(root)["valid"] is False


def test_tracked_source_symlink_with_matching_target_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("x", encoding="utf-8")
    (root / "source.py").symlink_to(outside)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "source.py"], check=True)
    _write_manifest(root, [file_record(outside, Path("source.py"), source=True)])

    assert VERIFY.verify(root)["valid"] is False


def test_duplicate_records_with_recalculated_valid_root_are_refused(tmp_path: Path) -> None:
    document = _fixture(tmp_path)
    records = document["files"]
    assert isinstance(records, list)
    _write_manifest(tmp_path, [records[0], records[0]])
    assert VERIFY.verify(tmp_path)["valid"] is False


@pytest.mark.parametrize("target", ["file_count", "bytes", "manifest_self_excluded"])
def test_source_manifest_rejects_boolean_type_confusion(tmp_path: Path, target: str) -> None:
    document = _fixture(tmp_path)
    if target == "bytes":
        records = document["files"]
        assert isinstance(records, list)
        records[0]["bytes"] = True
        document["root_sha256"] = manifest_root(records)
    elif target == "file_count":
        document["file_count"] = True
    else:
        document["manifest_self_excluded"] = False
    (tmp_path / "SOURCE_MANIFEST.json").write_text(json.dumps(document), encoding="utf-8")
    assert VERIFY.verify(tmp_path)["valid"] is False


@pytest.mark.parametrize(
    ("original", "poison"),
    [
        ('"kind": "source"', '"kind": "forged", "kind": "source"'),
        ('"path": "source.py"', '"path": "../escape.py", "path": "source.py"'),
    ],
)
def test_source_manifest_rejects_duplicate_json_keys(
    tmp_path: Path, original: str, poison: str
) -> None:
    _fixture(tmp_path)
    path = tmp_path / "SOURCE_MANIFEST.json"
    contents = path.read_text(encoding="utf-8")
    assert original in contents
    path.write_text(contents.replace(original, poison, 1), encoding="utf-8")
    assert VERIFY.verify(tmp_path)["valid"] is False


def test_source_manifest_refuses_reordered_valid_records(tmp_path: Path) -> None:
    document = _fixture(tmp_path)
    extra = tmp_path / "another.py"
    extra.write_text("y", encoding="utf-8")
    records = document["files"]
    assert isinstance(records, list)
    reversed_records = [records[0], file_record(extra, Path("another.py"), source=True)]
    _write_manifest(tmp_path, reversed_records)
    assert VERIFY.verify(tmp_path)["valid"] is False
