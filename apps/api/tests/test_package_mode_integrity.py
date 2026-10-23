from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


def _module(root: Path):
    script = root / "scripts" / "verify_package.py"
    spec = importlib.util.spec_from_file_location("verify_package", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_zip(path: Path, *, stored_mode: int, manifest_mode: int = 0o644) -> None:
    import hashlib

    payload = b"#!/bin/sh\nexit 0\n"
    record = {
        "path": "scripts/run.sh",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "mode": "0755",
    }
    manifest = {
        "schema": "korpus.distribution-manifest.v2",
        "kind": "distribution",
        "manifest_self_excluded": True,
        "file_count": 1,
        "root_sha256": hashlib.sha256(
            f"{record['path']}\0{record['mode']}\0{record['sha256']}\n".encode()
        ).hexdigest(),
        "files": [record],
    }
    with zipfile.ZipFile(path, "w") as zf:
        root = "KORPUS/"
        info = zipfile.ZipInfo(root + "scripts/run.sh")
        info.create_system = 3
        info.external_attr = (0o100000 | stored_mode) << 16
        zf.writestr(info, payload)
        mi = zipfile.ZipInfo(root + "DISTRIBUTION_MANIFEST.json")
        mi.create_system = 3
        mi.external_attr = (0o100000 | manifest_mode) << 16
        zf.writestr(mi, json.dumps(manifest).encode())


def test_package_verifier_accepts_preserved_executable_mode(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    archive = tmp_path / "good.zip"
    _write_zip(archive, stored_mode=0o755)
    failures, _ = module.verify(archive)
    assert failures == []


def test_package_verifier_refuses_lost_executable_mode(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    archive = tmp_path / "bad.zip"
    _write_zip(archive, stored_mode=0o644)
    failures, _ = module.verify(archive)
    assert any("mode mismatch: scripts/run.sh" in failure for failure in failures)


@pytest.mark.parametrize("special_mode", [0o4755, 0o2755, 0o1755])
def test_package_verifier_refuses_special_payload_mode_bits(
    tmp_path: Path, special_mode: int
) -> None:
    root = Path(__file__).resolve().parents[3]
    archive = tmp_path / f"special-{special_mode:o}.zip"
    _write_zip(archive, stored_mode=special_mode)

    failures, _ = _module(root).verify(archive)

    assert any("special permission bits rejected" in failure for failure in failures)


@pytest.mark.parametrize("special_mode", [0o4644, 0o2644, 0o1644])
def test_package_verifier_refuses_special_manifest_mode_bits(
    tmp_path: Path, special_mode: int
) -> None:
    root = Path(__file__).resolve().parents[3]
    archive = tmp_path / f"manifest-special-{special_mode:o}.zip"
    _write_zip(archive, stored_mode=0o755, manifest_mode=special_mode)

    failures, _ = _module(root).verify(archive)

    assert any("special permission bits rejected" in failure for failure in failures)


def _write_zip_with_intruder(path: Path) -> None:
    """The same archive, plus one file the manifest does not describe."""
    import hashlib

    payload = b"#!/bin/sh\nexit 0\n"
    manifest = {
        "schema": "korpus.distribution-manifest.v2",
        "kind": "distribution",
        "manifest_self_excluded": True,
        "file_count": 1,
        "root_sha256": "",
        "files": [],
    }
    record = {
        "path": "scripts/run.sh",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "mode": "0755",
    }
    manifest["files"] = [record]
    manifest["root_sha256"] = hashlib.sha256(
        f"{record['path']}\0{record['mode']}\0{record['sha256']}\n".encode()
    ).hexdigest()
    with zipfile.ZipFile(path, "w") as zf:
        root = "KORPUS/"
        info = zipfile.ZipInfo(root + "scripts/run.sh")
        info.create_system = 3
        info.external_attr = (0o100000 | 0o755) << 16
        zf.writestr(info, payload)
        intruder = zipfile.ZipInfo(root + "scripts/backdoor.py")
        intruder.create_system = 3
        intruder.external_attr = 0o100644 << 16
        zf.writestr(intruder, b"VALUE = 1\n")
        mi = zipfile.ZipInfo(root + "DISTRIBUTION_MANIFEST.json")
        mi.create_system = 3
        mi.external_attr = 0o100644 << 16
        zf.writestr(mi, json.dumps(manifest).encode())


def test_a_file_the_manifest_does_not_describe_is_named_not_just_counted(
    tmp_path: Path,
) -> None:
    """Негативний контроль на спрощення повідомлень.

    Порожній запис для неописаного файлу давав `mode mismatch: None expected=None` —
    по рядку на файл, і жоден не називав шляху. Прибравши цей шум, треба довести, що
    сам випадок і далі ловиться І НАЗИВАЄТЬСЯ: інакше замість шуму вийшла б тиша.
    """
    root = Path(__file__).resolve().parents[3]
    module = _module(root)
    archive = tmp_path / "intruded.zip"
    _write_zip_with_intruder(archive)
    failures, _ = module.verify(archive)
    assert any("scripts/backdoor.py" in failure for failure in failures), failures
    assert not any("None" in failure for failure in failures), failures
