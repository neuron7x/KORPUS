"""Source distributions reject opaque runtime evidence even with consistent hashes."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from scripts.manifest_paths import source_included
from scripts.verify_package import verify

ROOT = Path(__file__).resolve().parents[3]


def _build_zip(
    archive: Path, *, prefix: str, poisoned: bool, extra_member: str | None = None
) -> None:
    files = {"proof.txt": b"verified source"}
    if poisoned:
        files["evidence/registry.json"] = b'{"digest":"internally-consistent"}'
    if extra_member is not None:
        files[extra_member] = b"additional bound file"
    manifest = {
        "schema": "korpus.distribution-manifest.v2",
        "kind": "distribution",
        "files": [
            {
                "path": name,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "mode": "0644",
            }
            for name, body in sorted(files.items())
        ],
    }
    files["DISTRIBUTION_MANIFEST.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(archive, "w") as target:
        for name, body in files.items():
            info = zipfile.ZipInfo(prefix + name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            target.writestr(info, body)


@pytest.mark.parametrize("prefix", ["", "KORPUS/"])
@pytest.mark.parametrize("poisoned", [False, True])
def test_opaque_runtime_payload_fails_before_extraction(
    tmp_path: Path, prefix: str, poisoned: bool
) -> None:
    candidate = tmp_path / "candidate.zip"
    _build_zip(candidate, prefix=prefix, poisoned=poisoned)
    failures, files = verify(candidate)
    if poisoned:
        assert files == 0
        assert any("unverified runtime evidence forbidden" in item for item in failures)
    else:
        assert failures == []
        assert files == 2


def test_history_bundle_is_source_eligible() -> None:
    assert source_included(Path("history.bundle"))
    assert source_included(Path("subfolder/deleted-history.bundle"))


def test_producer_keeps_reports_but_never_copies_runtime_registry() -> None:
    producer = (ROOT / "scripts/package_repository.sh").read_text(encoding="utf-8")
    assert "cp -a reports" in producer
    assert "cp -a var/evidence" not in producer
    assert "cp -a var/releases" not in producer
    assert '[[ -e "$tmp/evidence" ]]' in producer


@pytest.mark.parametrize(
    "member",
    [
        "var/evidence/registry.json",
        "var/releases/object.json",
        "Evidence/registry.json",
        "EvIdEnCe/registry.json",
        "KORPUS/evidence/registry.json",
        "KORPUS/var/releases/object.json",
        "KORPUS/EVIDENCE/registry.json",
        "other/var/ReLeAsEs/object.json",
        "other/Evidence/registry.json",
    ],
)
def test_runtime_path_alias_and_multiroot_poison(tmp_path: Path, member: str) -> None:
    archive = tmp_path / "poison.zip"
    _build_zip(archive, prefix="", poisoned=False, extra_member=member)
    failures, count = verify(archive)
    assert count == 0
    assert any("unverified runtime evidence forbidden" in failure for failure in failures)


def test_authorized_handoff_evidence_is_not_misclassified(tmp_path: Path) -> None:
    archive = tmp_path / "handoff.zip"
    _build_zip(
        archive,
        prefix="",
        poisoned=False,
        extra_member="handoff/evidence/current/MANIFEST.json",
    )
    failures, count = verify(archive)
    assert failures == []
    assert count == 3


@pytest.mark.parametrize(
    "member",
    [
        "reports/release/v0.8.0/evidence/report.json",
        "KORPUS/reports/release/v0.8.0/evidence/report.json",
    ],
)
def test_release_report_evidence_remains_admitted(tmp_path: Path, member: str) -> None:
    archive = tmp_path / "report.zip"
    _build_zip(archive, prefix="", poisoned=False, extra_member=member)
    failures, count = verify(archive)
    assert failures == []
    assert count == 3


@pytest.mark.parametrize(
    "member",
    [
        "evidence./registry.json",
        "evidence /registry.json",
        "var/releases./object.json",
        "KORPUS/Evidence./registry.json",
        "KORPUS/var/RELEASES /object.json",
    ],
)
def test_windows_path_aliases_cannot_hide_opaque_evidence(tmp_path: Path, member: str) -> None:
    archive = tmp_path / "windows-alias.zip"
    _build_zip(archive, prefix="", poisoned=False, extra_member=member)
    failures, count = verify(archive)
    assert count == 0
    assert any("unverified runtime evidence forbidden" in failure for failure in failures)
