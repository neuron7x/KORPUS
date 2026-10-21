"""Deterministic archive-path replacement controls for issue #22."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.manifest_lib.integrity import manifest_root

ROOT = Path(__file__).resolve().parents[3]


def _verifier():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "verify_package_archive_identity", ROOT / "scripts/verify_package.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_zip(path: Path) -> None:
    body = b"verified artifact bytes\n"
    manifest = {
        "schema": "korpus.distribution-manifest.v2",
        "kind": "distribution",
        "files": [
            {
                "path": "proof.txt",
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "mode": "0644",
            }
        ],
    }
    records = manifest["files"]
    manifest.update(
        manifest_self_excluded=True,
        file_count=len(records),
        root_sha256=manifest_root(records),
    )
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in (
            ("KORPUS/proof.txt", body),
            ("KORPUS/DISTRIBUTION_MANIFEST.json", json.dumps(manifest).encode()),
        ):
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            zf.writestr(info, content)


def test_unmodified_verified_zip_digest_matches_exact_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "normal.zip"
    _valid_zip(archive)
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    module = _verifier()
    monkeypatch.setattr(sys, "argv", ["verify_package.py", str(archive)])
    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["valid"] is True
    assert result["files"] == 2
    assert result["sha256"] == expected


@pytest.mark.parametrize("valid_original", [True, False])
def test_path_swap_cannot_split_semantics_from_reported_sha256(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    valid_original: bool,
) -> None:
    archive = tmp_path / "candidate.zip"
    replacement = tmp_path / "replacement.zip"
    if valid_original:
        _valid_zip(archive)
        replacement.write_bytes(b"invalid replacement, not a ZIP")
    else:
        archive.write_bytes(b"invalid original, not a ZIP")
        _valid_zip(replacement)
    admitted_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    module = _verifier()
    original_verifier = module.verify

    def replace_between_snapshot_and_verification(snapshot):
        # The pathname becomes a different object after the trusted descriptor is copied.
        archive.unlink()
        replacement.replace(archive)
        return original_verifier(snapshot)

    monkeypatch.setattr(module, "verify", replace_between_snapshot_and_verification)
    monkeypatch.setattr(sys, "argv", ["verify_package.py", str(archive)])
    status = module.main()
    report = json.loads(capsys.readouterr().out)
    assert report["valid"] is valid_original
    assert status == (0 if valid_original else 1)
    assert report["sha256"] == admitted_sha
    assert hashlib.sha256(archive.read_bytes()).hexdigest() != admitted_sha
