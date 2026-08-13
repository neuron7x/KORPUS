#!/usr/bin/env python3
"""Build signed-release metadata only from one completed package artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

BUILD_MEMBER = "PACKAGE_BUILD.json"
RELEASE_MEMBER = "apps/api/src/korpus/release.json"
SOURCE_MANIFEST_MEMBER = "SOURCE_MANIFEST.json"
PRODUCTION_ASSURANCE_MEMBER = "reports/PRODUCTION_ASSURANCE_REPORT.json"
PRODUCTION_ASSURANCE_ATTESTATION_MEMBER = "reports/PRODUCTION_ASSURANCE_REPORT.attestation.json"
_SHA40 = re.compile(r"[0-9a-f]{40}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_name(name: str) -> str:
    return name[2:] if name.startswith("./") else name


def _member_bytes(archive: zipfile.ZipFile, name: str) -> bytes:
    matches = [
        info
        for info in archive.infolist()
        if not info.is_dir() and _canonical_name(info.filename) == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"package must contain exactly one {name}; found {len(matches)}")
    return archive.read(matches[0])


def _json_object(data: bytes, name: str) -> dict[str, object]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"package member is not valid JSON: {name}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"package member is not a JSON object: {name}")
    return value


def _source_commit(build: dict[str, object], expected: str | None) -> str:
    value = build.get("source_commit")
    if build.get("schema") != "korpus.package-build.v1":
        raise RuntimeError("invalid package build metadata schema")
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise RuntimeError("package build metadata has invalid source commit")
    if expected is not None and value != expected:
        raise RuntimeError("package source commit does not match expected build commit")
    return value


def _release(
    identity: dict[str, object], assurance: dict[str, object], expected: str | None
) -> str:
    value = identity.get("tag")
    if not isinstance(value, str) or not value:
        raise RuntimeError("packaged release identity has no tag")
    if expected is not None and value != expected:
        raise RuntimeError("packaged release identity does not match expected release")
    if assurance.get("release") != value:
        raise RuntimeError("production assurance release does not match packaged release identity")
    if assurance.get("status") != "PASS" or assurance.get("production_authorized") is not True:
        raise RuntimeError("packaged production assurance is not authorized PASS evidence")
    return value


def _verified_hash(data: bytes, expected: str | None, mismatch: str) -> str:
    actual = _sha256(data)
    if expected is not None and actual != expected:
        raise RuntimeError(mismatch)
    return actual


def build_release_manifest(
    artifact: Path,
    *,
    expected_source_commit: str | None = None,
    expected_release: str | None = None,
    expected_assurance_sha256: str | None = None,
    expected_assurance_attestation_sha256: str | None = None,
) -> dict[str, object]:
    """Describe immutable package bytes; mutable checkout state is not consulted."""
    artifact = artifact.resolve()
    if not artifact.is_file():
        raise RuntimeError(f"release artifact is missing: {artifact}")
    with zipfile.ZipFile(artifact) as archive:
        build = _json_object(_member_bytes(archive, BUILD_MEMBER), BUILD_MEMBER)
        identity = _json_object(_member_bytes(archive, RELEASE_MEMBER), RELEASE_MEMBER)
        source_manifest_bytes = _member_bytes(archive, SOURCE_MANIFEST_MEMBER)
        assurance_bytes = _member_bytes(archive, PRODUCTION_ASSURANCE_MEMBER)
        attestation_bytes = _member_bytes(archive, PRODUCTION_ASSURANCE_ATTESTATION_MEMBER)

    assurance = _json_object(assurance_bytes, PRODUCTION_ASSURANCE_MEMBER)
    source_commit = _source_commit(build, expected_source_commit)
    release = _release(identity, assurance, expected_release)
    assurance_sha256 = _verified_hash(
        assurance_bytes,
        expected_assurance_sha256,
        "packaged production assurance differs from verified assurance bytes",
    )
    attestation_sha256 = _verified_hash(
        attestation_bytes,
        expected_assurance_attestation_sha256,
        "packaged production assurance attestation differs from verified bytes",
    )
    return {
        "schema": "korpus.signed-release-manifest.v1",
        "release": release,
        "git_commit": source_commit,
        "artifact": artifact.name,
        "artifact_sha256": _sha256(artifact.read_bytes()),
        "source_manifest_sha256": _sha256(source_manifest_bytes),
        "production_assurance_sha256": assurance_sha256,
        "production_assurance_attestation_sha256": attestation_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-source-commit")
    parser.add_argument("--expected-release")
    parser.add_argument("--expected-assurance-sha256", required=True)
    parser.add_argument("--expected-assurance-attestation-sha256", required=True)
    args = parser.parse_args()
    try:
        payload = build_release_manifest(
            args.artifact,
            expected_source_commit=args.expected_source_commit,
            expected_release=args.expected_release,
            expected_assurance_sha256=args.expected_assurance_sha256,
            expected_assurance_attestation_sha256=args.expected_assurance_attestation_sha256,
        )
    except (RuntimeError, OSError, zipfile.BadZipFile) as error:
        raise SystemExit(str(error)) from error
    args.out.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
