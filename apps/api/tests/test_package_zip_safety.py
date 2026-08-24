from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _module():
    sys.path.insert(0, str(ROOT / "scripts"))
    script = ROOT / "scripts" / "verify_package.py"
    spec = importlib.util.spec_from_file_location("verify_package_zip_safety", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safety_module():
    sys.path.insert(0, str(ROOT / "scripts"))
    script = ROOT / "scripts" / "zip_safety.py"
    spec = importlib.util.spec_from_file_location("zip_safety_resource_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(payload: bytes) -> bytes:
    return json.dumps({
        "schema": "korpus.distribution-manifest.v2",
        "kind": "distribution",
        "files": [{
            "path": "payload.txt",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "mode": "0644",
        }],
    }).encode()


def _info(name: str, mode: int = stat.S_IFREG | 0o644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = mode << 16
    return info


def _valid_archive(path: Path) -> None:
    payload = b"safe\n"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(_info("KORPUS/payload.txt"), payload)
        zf.writestr(_info("KORPUS/DISTRIBUTION_MANIFEST.json"), _manifest(payload))


def test_valid_archive_remains_accepted(tmp_path: Path) -> None:
    archive = tmp_path / "valid.zip"
    _valid_archive(archive)
    failures, count = _module().verify(archive)
    assert failures == []
    assert count == 2


def test_parent_traversal_is_rejected_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "traversal.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_info("../escape.txt"), b"x")
    failures, count = _module().verify(archive)
    assert count == 0
    assert any("non-canonical archive path rejected" in item for item in failures)


def test_duplicate_name_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_info("same.txt"), b"a")
        zf.writestr(_info("same.txt"), b"b")
    failures, _ = _module().verify(archive)
    assert any("duplicate archive entry rejected" in item for item in failures)


def test_casefold_alias_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "casefold.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_info("A.txt"), b"a")
        zf.writestr(_info("a.txt"), b"b")
    failures, _ = _module().verify(archive)
    assert any("casefold/alias collision rejected" in item for item in failures)


def test_symlink_entry_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_info("link", stat.S_IFLNK | 0o777), b"target")
    failures, _ = _module().verify(archive)
    assert any("non-regular archive entry rejected" in item for item in failures)


def test_backslash_alias_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "backslash.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_info(r"dir\\escape.txt"), b"x")
    failures, _ = _module().verify(archive)
    assert any("backslash path separator rejected" in item for item in failures)


def test_nested_distribution_manifest_is_not_an_unbound_blind_spot(tmp_path: Path) -> None:
    archive = tmp_path / "nested-manifest.zip"
    nested = b'{"inner":true}\n'
    record = {
        "path": "KORPUS_SOURCE/DISTRIBUTION_MANIFEST.json",
        "bytes": len(nested),
        "sha256": hashlib.sha256(nested).hexdigest(),
        "mode": "0644",
    }
    outer = json.dumps({
        "schema": "korpus.distribution-manifest.v2",
        "kind": "distribution",
        "files": [record],
    }).encode()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_info("KORPUS_SOURCE/DISTRIBUTION_MANIFEST.json"), nested)
        zf.writestr(_info("DISTRIBUTION_MANIFEST.json"), outer)

    failures, count = _module().verify(archive)

    assert failures == []
    assert count == 2


def test_entry_count_budget_refuses_before_structural_processing(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "too-many.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_info("a.txt"), b"a")
        zf.writestr(_info("b.txt"), b"b")
    module = _safety_module()
    policy = sys.modules[module.resource_failures.__module__]
    monkeypatch.setattr(policy, "MAX_ARCHIVE_ENTRIES", 1)
    monkeypatch.setattr(module, "_record_entry", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("structural parser ran")
    ))
    with zipfile.ZipFile(archive) as zf:
        failures = module.safety_failures(zf)
    assert any("entry budget exceeded" in item for item in failures)


def test_per_entry_uncompressed_budget_is_enforced(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "large-entry.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_info("payload.txt"), b"12345")
    module = _safety_module()
    monkeypatch.setattr(sys.modules[module.resource_failures.__module__], "MAX_ENTRY_UNCOMPRESSED_BYTES", 4)
    with zipfile.ZipFile(archive) as zf:
        safety = module.safety_failures(zf)
    assert any("entry uncompressed budget exceeded" in item for item in safety)


def test_total_uncompressed_budget_is_enforced(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "large-total.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_info("a.txt"), b"1234")
        zf.writestr(_info("b.txt"), b"5678")
    module = _safety_module()
    monkeypatch.setattr(sys.modules[module.resource_failures.__module__], "MAX_TOTAL_UNCOMPRESSED_BYTES", 7)
    with zipfile.ZipFile(archive) as zf:
        safety = module.safety_failures(zf)
    assert any("total uncompressed budget exceeded" in item for item in safety)


def test_compression_ratio_budget_is_enforced(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "ratio.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zeros.txt", b"0" * 4096)
    module = _safety_module()
    monkeypatch.setattr(sys.modules[module.resource_failures.__module__], "MAX_COMPRESSION_RATIO", 2.0)
    with zipfile.ZipFile(archive) as zf:
        safety = module.safety_failures(zf)
    assert any("compression ratio exceeded" in item for item in safety)
