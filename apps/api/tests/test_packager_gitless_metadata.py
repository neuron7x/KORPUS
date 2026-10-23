"""Packaging must preserve the canonical gitless v2 identity, not synthesize v1."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

from scripts.verify_package_build_identity import verify

ROOT = Path(__file__).resolve().parents[3]


def test_packager_preserves_archived_v2_and_requires_identity_gate(tmp_path: Path) -> None:
    script = (ROOT / "scripts/package_repository.sh").read_text(encoding="utf-8")
    assert "korpus.package-build.v1" not in script
    gate = 'python3 "$root/scripts/verify_package_build_identity.py" --root "$tmp"'
    assert script.count(gate) == 2

    source = tmp_path / "source"
    identity = source / "apps/api/src/korpus/release.json"
    identity.parent.mkdir(parents=True)
    identity.write_text(
        json.dumps(
            {
                "schema": "korpus.release-identity.v1",
                "product": "KORPUS",
                "version": "0.1.0",
                "tag": "v0.1.0",
                "artifact_stem": "KORPUS_TEST_v0.1.0",
                "distribution_artifact": "KORPUS_TEST_v0.1.0.zip",
            }
        )
    )
    manifest = {"schema": "korpus.source-manifest.v2", "root_sha256": "a" * 64}
    (source / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    metadata = {
        "schema": "korpus.package-build.v2",
        "release": "v0.1.0",
        "source_manifest_root_sha256": "a" * 64,
        "history_included": False,
        "source_commit": None,
        "import_required_to_obtain_git_commit": True,
        "derived_from_source_commit": None,
    }
    (source / "PACKAGE_BUILD.json").write_text(json.dumps(metadata))
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "source",
        ],
        check=True,
    )
    archive = subprocess.run(
        ["git", "-C", str(source), "archive", "--format=tar", "HEAD"],
        check=True,
        capture_output=True,
    ).stdout
    stage = tmp_path / "stage"
    stage.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(stage, filter="data")
    assert (stage / "PACKAGE_BUILD.json").read_bytes() == (
        source / "PACKAGE_BUILD.json"
    ).read_bytes()
    assert verify(stage) == []

    # The precise old producer output must fail the actual consumer.
    (stage / "PACKAGE_BUILD.json").write_text(
        json.dumps(
            {
                "schema": "korpus.package-build.v1",
                "source_commit": "b" * 40,
                "release": "v0.1.0",
                "history_included": False,
            }
        )
    )
    failures = verify(stage)
    assert "package build schema mismatch" in failures
    assert "gitless canonical package must not invent a source commit" in failures
