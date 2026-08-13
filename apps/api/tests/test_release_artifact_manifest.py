"""Signed release metadata must come from one immutable package artifact."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from scripts.manifest_paths import source_included
from scripts.release_artifact_manifest import build_release_manifest
from scripts.signed_manifest_identity import manifest_release

COMMIT = "a" * 40
RELEASE = "v0.1.1"
ASSURANCE = "reports/PRODUCTION_ASSURANCE_REPORT.json"
ASSURANCE_ATTESTATION = "reports/PRODUCTION_ASSURANCE_REPORT.attestation.json"


def _members(
    *,
    commit: str = COMMIT,
    release: str = RELEASE,
    assurance_release: str = RELEASE,
    assurance_status: str = "PASS",
    production_authorized: bool = True,
) -> dict[str, bytes]:
    return {
        "PACKAGE_BUILD.json": json.dumps(
            {"schema": "korpus.package-build.v1", "source_commit": commit}
        ).encode(),
        "apps/api/src/korpus/release.json": json.dumps(
            {"schema": "korpus.release-identity.v1", "tag": release}
        ).encode(),
        "SOURCE_MANIFEST.json": b'{"schema":"korpus.source-manifest.v2"}\n',
        ASSURANCE: json.dumps(
            {
                "schema": "korpus.production-assurance.v1",
                "release": assurance_release,
                "status": assurance_status,
                "production_authorized": production_authorized,
            }
        ).encode(),
        ASSURANCE_ATTESTATION: b'{"schema":"korpus.release-attestation.v1"}\n',
    }


def _artifact(tmp_path: Path, members: dict[str, bytes] | None = None) -> Path:
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in (members or _members()).items():
            zf.writestr(name, content)
    return archive


def test_manifest_is_derived_from_exact_artifact_members(tmp_path: Path) -> None:
    members = _members()
    archive = _artifact(tmp_path, members)
    payload = build_release_manifest(
        archive,
        expected_source_commit=COMMIT,
        expected_release=RELEASE,
        expected_assurance_sha256=hashlib.sha256(members[ASSURANCE]).hexdigest(),
        expected_assurance_attestation_sha256=hashlib.sha256(
            members[ASSURANCE_ATTESTATION]
        ).hexdigest(),
    )

    assert payload == {
        "schema": "korpus.signed-release-manifest.v1",
        "release": RELEASE,
        "git_commit": COMMIT,
        "artifact": archive.name,
        "artifact_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "source_manifest_sha256": hashlib.sha256(members["SOURCE_MANIFEST.json"]).hexdigest(),
        "production_assurance_sha256": hashlib.sha256(members[ASSURANCE]).hexdigest(),
        "production_assurance_attestation_sha256": hashlib.sha256(
            members[ASSURANCE_ATTESTATION]
        ).hexdigest(),
    }


def test_checkout_files_cannot_change_metadata_after_artifact_exists(tmp_path: Path) -> None:
    archive = _artifact(tmp_path)
    baseline = build_release_manifest(archive)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    for name in ("SOURCE_MANIFEST.json", "PRODUCTION_ASSURANCE_REPORT.json", "release.json"):
        (checkout / name).write_text("mutated after build\n", encoding="utf-8")
    assert build_release_manifest(archive) == baseline


@pytest.mark.parametrize(
    "missing",
    [
        "PACKAGE_BUILD.json",
        "apps/api/src/korpus/release.json",
        "SOURCE_MANIFEST.json",
        ASSURANCE,
        ASSURANCE_ATTESTATION,
    ],
)
def test_missing_canonical_member_is_rejected(tmp_path: Path, missing: str) -> None:
    members = _members()
    del members[missing]
    archive = _artifact(tmp_path, members)
    with pytest.raises(RuntimeError, match="exactly one"):
        build_release_manifest(archive)


def test_duplicate_canonical_member_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, content in _members().items():
            zf.writestr(name, content)
        zf.writestr("./SOURCE_MANIFEST.json", b"duplicate")
    with pytest.raises(RuntimeError, match="SOURCE_MANIFEST.json; found 2"):
        build_release_manifest(archive)


def test_wrong_expected_source_commit_is_rejected(tmp_path: Path) -> None:
    archive = _artifact(tmp_path)
    with pytest.raises(RuntimeError, match="expected build commit"):
        build_release_manifest(archive, expected_source_commit="b" * 40)


def test_invalid_embedded_source_commit_is_rejected(tmp_path: Path) -> None:
    archive = _artifact(tmp_path, _members(commit="not-a-commit"))
    with pytest.raises(RuntimeError, match="invalid source commit"):
        build_release_manifest(archive)


def test_wrong_expected_release_is_rejected(tmp_path: Path) -> None:
    archive = _artifact(tmp_path)
    with pytest.raises(RuntimeError, match="expected release"):
        build_release_manifest(archive, expected_release="v9.9.9")


def test_production_assurance_must_match_packaged_release(tmp_path: Path) -> None:
    archive = _artifact(tmp_path, _members(assurance_release="v9.9.9"))
    with pytest.raises(RuntimeError, match="production assurance release"):
        build_release_manifest(archive)


@pytest.mark.parametrize(
    "members",
    [
        _members(assurance_status="FAIL"),
        _members(production_authorized=False),
    ],
)
def test_non_authorized_assurance_cannot_be_signed(
    tmp_path: Path, members: dict[str, bytes]
) -> None:
    archive = _artifact(tmp_path, members)
    with pytest.raises(RuntimeError, match="not authorized PASS"):
        build_release_manifest(archive)


def test_packaged_assurance_must_equal_verified_report_bytes(tmp_path: Path) -> None:
    archive = _artifact(tmp_path)
    with pytest.raises(RuntimeError, match="differs from verified assurance bytes"):
        build_release_manifest(archive, expected_assurance_sha256="b" * 64)


def test_packaged_assurance_attestation_must_equal_verified_bytes(tmp_path: Path) -> None:
    archive = _artifact(tmp_path)
    with pytest.raises(RuntimeError, match="attestation differs from verified bytes"):
        build_release_manifest(
            archive, expected_assurance_attestation_sha256="b" * 64
        )


def test_attestation_identity_comes_from_signed_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"release": "v7.8.9"}), encoding="utf-8")
    assert manifest_release(manifest) == "v7.8.9"


def test_attestation_identity_without_release_fails_closed(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no release identity"):
        manifest_release(manifest)


def test_package_build_metadata_is_not_part_of_source_snapshot() -> None:
    assert source_included(Path("PACKAGE_BUILD.json")) is False
    assert source_included(Path("docs/PACKAGE_BUILD.json")) is True
