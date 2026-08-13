"""A release package must have one canonical archive and manifest inventory."""
from __future__ import annotations

import json
import stat
import warnings
import zipfile
from pathlib import Path

import pytest
from scripts.generate_manifest import write_manifest
from scripts.manifest_lib.package_inventory import (
    archive_inventory_failures,
    canonical_member_name,
    load_distribution_records,
)
from scripts.verify_package import verify


def _zip(tmp_path: Path, entries: list[tuple[str, bytes]]) -> Path:
    archive = tmp_path / "fixture.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(archive, "w") as zf:
            for name, content in entries:
                zf.writestr(name, content)
    return archive


def test_canonical_relative_posix_member_is_accepted() -> None:
    assert canonical_member_name("apps/api/src/korpus/policy.py") == "apps/api/src/korpus/policy.py"
    assert canonical_member_name("reports/") is None
    assert canonical_member_name("reports/", directory=True) == "reports"


@pytest.mark.parametrize(
    "name",
    [
        "./apps/api.py",
        "apps/../api.py",
        "apps/./api.py",
        "../outside",
        "/absolute",
        "dir\\alias.py",
        "C:/windows-drive.py",
    ],
)
def test_noncanonical_member_names_are_rejected(name: str) -> None:
    assert canonical_member_name(name) is None


def test_duplicate_zip_member_is_rejected_before_extraction(tmp_path: Path) -> None:
    archive = _zip(tmp_path, [("source.txt", b"first"), ("source.txt", b"second")])
    failures, files = verify(archive)
    assert files == 0
    assert any("duplicate archive member" in failure for failure in failures)


def test_archive_alias_is_rejected_before_extraction(tmp_path: Path) -> None:
    archive = _zip(tmp_path, [("source.txt", b"one"), ("./source.txt", b"two")])
    failures, files = verify(archive)
    assert files == 0
    assert any("non-canonical archive member" in failure for failure in failures)


def test_archive_inventory_rejects_directory_file_collision(tmp_path: Path) -> None:
    archive = _zip(tmp_path, [("node/", b""), ("node", b"file")])
    with zipfile.ZipFile(archive) as zf:
        failures = archive_inventory_failures(zf)
    assert any("duplicate archive member" in failure for failure in failures)


def test_explicit_symlink_member_is_rejected_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, "target")

    failures, files = verify(archive)
    assert files == 0
    assert "unsupported archive member type: 'link'" in failures


def test_directory_name_with_regular_unix_type_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "directory-name-regular-mode.zip"
    info = zipfile.ZipInfo("node/")
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, b"")

    failures, files = verify(archive)
    assert files == 0
    assert "archive member name/type mismatch: 'node/'" in failures


def test_file_name_with_directory_unix_type_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "file-name-directory-mode.zip"
    info = zipfile.ZipInfo("node")
    info.create_system = 3
    info.external_attr = (stat.S_IFDIR | 0o755) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, b"")

    failures, files = verify(archive)
    assert files == 0
    assert "archive member name/type mismatch: 'node'" in failures


def _distribution_root(tmp_path: Path) -> Path:
    root = tmp_path / "distribution"
    root.mkdir()
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    write_manifest(root, root / "DISTRIBUTION_MANIFEST.json", kind="distribution")
    return root


def _manifest(root: Path) -> dict[str, object]:
    return json.loads((root / "DISTRIBUTION_MANIFEST.json").read_text(encoding="utf-8"))


def _write_manifest_payload(root: Path, payload: dict[str, object]) -> None:
    (root / "DISTRIBUTION_MANIFEST.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def test_generated_distribution_inventory_is_accepted(tmp_path: Path) -> None:
    failures, records = load_distribution_records(_distribution_root(tmp_path))
    assert failures == []
    assert tuple(records) == ("a.txt",)


def test_duplicate_distribution_record_is_rejected(tmp_path: Path) -> None:
    root = _distribution_root(tmp_path)
    payload = _manifest(root)
    records = payload["files"]
    assert isinstance(records, list)
    records.append(dict(records[0]))
    _write_manifest_payload(root, payload)

    failures, _ = load_distribution_records(root)
    assert any("duplicate distribution manifest record" in failure for failure in failures)


def test_distribution_file_count_lie_is_rejected(tmp_path: Path) -> None:
    root = _distribution_root(tmp_path)
    payload = _manifest(root)
    payload["file_count"] = 999
    _write_manifest_payload(root, payload)

    failures, _ = load_distribution_records(root)
    assert "manifest aggregate integrity mismatch" in failures


def test_distribution_root_digest_lie_is_rejected(tmp_path: Path) -> None:
    root = _distribution_root(tmp_path)
    payload = _manifest(root)
    payload["root_sha256"] = "0" * 64
    _write_manifest_payload(root, payload)

    failures, _ = load_distribution_records(root)
    assert "manifest aggregate integrity mismatch" in failures


def test_noncanonical_distribution_record_path_is_rejected(tmp_path: Path) -> None:
    root = _distribution_root(tmp_path)
    payload = _manifest(root)
    records = payload["files"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    record["path"] = "../a.txt"
    _write_manifest_payload(root, payload)

    failures, _ = load_distribution_records(root)
    assert any("non-canonical distribution record path" in failure for failure in failures)
