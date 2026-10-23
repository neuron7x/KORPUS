"""Source distributions reject opaque runtime evidence even with consistent hashes."""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.manifest_lib.integrity import manifest_root
from scripts.manifest_paths import source_included
from scripts.verify_package import verify

ROOT = Path(__file__).resolve().parents[3]


def _build_zip(
    archive: Path,
    *,
    prefix: str,
    poisoned: bool,
    extra_member: str | None = None,
    extra_payload: bytes = b"additional bound file",
) -> None:
    files = {"proof.txt": b"verified source"}
    if poisoned:
        files["evidence/registry.json"] = b'{"digest":"internally-consistent"}'
    if extra_member is not None:
        files[extra_member] = extra_payload
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
    records = manifest["files"]
    manifest.update(
        manifest_self_excluded=True,
        file_count=len(records),
        root_sha256=manifest_root(records),
    )
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
    assert "history bundle forbidden in canonical package" in producer
    assert "not independently authenticated as a set" in producer
    assert "verified release reports" not in producer


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
        "reports/evidence/registry.json",
        "reports/staged/evidence/registry.json",
        "KORPUS/reports/evidence/registry.json",
        "KORPUS/reports/staged/evidence/registry.json",
        "evidence/reports/release/registry.json",
        "evidence/handoff/evidence/registry.json",
        "KORPUS/evidence/reports/release/registry.json",
        "KORPUS/evidence/handoff/evidence/registry.json",
    ],
)
def test_runtime_path_alias_and_multiroot_poison(tmp_path: Path, member: str) -> None:
    archive = tmp_path / "poison.zip"
    _build_zip(archive, prefix="", poisoned=False, extra_member=member)
    failures, count = verify(archive)
    assert count == 0
    assert any("unverified runtime evidence forbidden" in failure for failure in failures)


@pytest.mark.parametrize("member", ["history.bundle", "KORPUS/history.bundle", "HISTORY.BUNDLE."])
def test_history_bundles_fail_even_with_consistent_manifest(tmp_path: Path, member: str) -> None:
    archive = tmp_path / "bundled-history.zip"
    _build_zip(archive, prefix="", poisoned=False, extra_member=member)
    failures, count = verify(archive)
    assert count == 0
    assert any("bundle forbidden" in failure for failure in failures)


def test_producer_rejects_staged_bundle_without_changing_clean_files(
    tmp_path: Path,
) -> None:
    producer = (ROOT / "scripts/package_repository.sh").read_text(encoding="utf-8")
    marker = "# A tracked bundle is source-digest-eligible"
    guard = marker + producer.split(marker, 1)[1].split("# Opaque local runtime evidence", 1)[0]
    command = 'set -euo pipefail\ntmp="$1"\n' + guard

    def status() -> int:
        return subprocess.run(
            ["bash", "-c", command, "bundle-guard", str(tmp_path)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        ).returncode

    (tmp_path / "safe.txt").write_bytes(b"clean")
    assert status() == 0
    for name, payload in (
        ("history.bundle", b"synthetic historical blob"),
        ("HISTORY.BUNDLE.", b"synthetic historical blob"),
        ("history.dat", b"# v2 git bundle\nsynthetic refs"),
        ("history.bin", b"# v3 git bundle\nsynthetic refs"),
    ):
        path = tmp_path / name
        path.write_bytes(payload)
        assert status() == 1
        path.unlink()


@pytest.mark.parametrize("header", [b"# v2 git bundle\n", b"# v3 git bundle\n"])
def test_disguised_bundle_magic_is_rejected(tmp_path: Path, header: bytes) -> None:
    archive = tmp_path / "disguised.zip"
    _build_zip(
        archive,
        prefix="",
        poisoned=False,
        extra_member="reports/release/v0.8.0/history.dat",
        extra_payload=header + b"synthetic history",
    )
    failures, count = verify(archive)
    assert count == 0
    assert any("git bundle forbidden" in failure for failure in failures)


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


@pytest.mark.parametrize("component", ["", ".", "..", "...", " ", " . "])
def test_normalized_empty_components_are_refused(component: str) -> None:
    from scripts.distribution_runtime_policy import _opaque_path

    assert _opaque_path(f"documents/{component}/file.txt")


@pytest.mark.parametrize(
    "path",
    [
        "docs/README.md",
        "reports/release/v0.9.7/evidence/report.json",
        "KORPUS/reports/release/v0.9.7/evidence/report.json",
        "handoff/evidence/current/MANIFEST.json",
        "KORPUS/handoff/evidence/current/MANIFEST.json",
    ],
)
def test_normalized_path_guard_preserves_allowed_contracts(path: str) -> None:
    from scripts.distribution_runtime_policy import _opaque_path

    assert not _opaque_path(path)


def test_runtime_policy_imports_in_isolated_process() -> None:
    command = (
        "import sys; sys.path.insert(0, '.'); "
        "from scripts.distribution_runtime_policy import _opaque_path; "
        "assert _opaque_path('var/evidence/registry.json'); "
        "assert not _opaque_path('reports/release/v1/evidence/report.json')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
