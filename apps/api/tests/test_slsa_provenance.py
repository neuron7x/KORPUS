from __future__ import annotations

import json
from pathlib import Path

from scripts.slsa_provenance import LOCAL_BUILDER, build_statement, verify_statement


def seed(root: Path) -> Path:
    files = {
        "SOURCE_MANIFEST.json": "{}\n",
        "apps/api/src/korpus/release.json": json.dumps({
            "schema": "korpus.release-identity.v1",
            "product": "KORPUS",
            "version": "0.4.0",
            "tag": "v0.4.0",
            "artifact_stem": "KORPUS_SYSTEM_v0.4.0",
        }) + "\n",
        "apps/api/requirements.runtime.lock": "runtime\n",
        "apps/api/requirements.dev.lock": "dev\n",
        "apps/web/package-lock.json": "{}\n",
        "apps/api/Dockerfile": "FROM scratch\n",
        "apps/web/Dockerfile": "FROM scratch\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    artifact = root / "dist/KORPUS_SYSTEM_v0.4.0.zip"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"canonical artifact bytes")
    return artifact


def test_slsa_statement_binds_artifact_and_every_required_material(tmp_path: Path) -> None:
    artifact = seed(tmp_path)
    statement = build_statement(
        tmp_path,
        artifact,
        builder_id=LOCAL_BUILDER,
        invocation_id="test-invocation",
        started_on="2026-08-15T12:00:00Z",
        finished_on="2026-08-15T12:00:01Z",
    )
    verdict = verify_statement(
        tmp_path,
        artifact,
        statement,
        trusted_builders=set(),
        require_trusted_builder=False,
    )
    assert verdict["status"] == "PASS", verdict["failures"]
    assert verdict["slsa_level_claimed"] is False


def test_tampered_artifact_is_rejected(tmp_path: Path) -> None:
    artifact = seed(tmp_path)
    statement = build_statement(
        tmp_path,
        artifact,
        builder_id=LOCAL_BUILDER,
        invocation_id="test",
        started_on="2026-08-15T12:00:00Z",
        finished_on="2026-08-15T12:00:01Z",
    )
    artifact.write_bytes(b"tampered")
    verdict = verify_statement(tmp_path, artifact, statement, trusted_builders=set(), require_trusted_builder=False)
    assert verdict["status"] == "FAIL"
    assert "subject.digest" in verdict["failures"]


def test_local_builder_cannot_satisfy_production_trust(tmp_path: Path) -> None:
    artifact = seed(tmp_path)
    statement = build_statement(
        tmp_path,
        artifact,
        builder_id=LOCAL_BUILDER,
        invocation_id="test",
        started_on="2026-08-15T12:00:00Z",
        finished_on="2026-08-15T12:00:01Z",
    )
    verdict = verify_statement(tmp_path, artifact, statement, trusted_builders=set(), require_trusted_builder=True)
    assert verdict["status"] == "FAIL"
    assert "builder.trusted" in verdict["failures"]
