from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.main import create_app
from korpus.security.auth import get_identity

from apps.api.tests.security_fixtures import controlled_security_kwargs, write_calibration_bundle

ROOT = Path(__file__).resolve().parents[3]


def admin() -> Identity:
    return Identity(
        subject="infra-admin",
        roles=frozenset({"admin", "user", "auditor"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )


def test_static_infrastructure_contract_passes():
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_infrastructure.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_metrics_token_is_fail_closed(tmp_path: Path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'metrics.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="metrics-audit-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        metrics_token="metrics-secret",
    )
    app = create_app(settings)
    app.dependency_overrides[get_identity] = admin
    with TestClient(app) as client:
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
        response = client.get("/metrics", headers={"Authorization": "Bearer metrics-secret"})
        assert response.status_code == 200
        assert "korpus_http_requests_total" in response.text


def test_readiness_fails_when_anchor_backlog_exceeds_budget(tmp_path: Path, monkeypatch):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'backlog.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="backlog-audit-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        audit_max_pending_events=0,
        audit_reconcile_interval_seconds=60,
    )
    app = create_app(settings)
    app.dependency_overrides[get_identity] = admin
    with TestClient(app) as client:
        repository = client.app.state.repository

        def unavailable(*args, **kwargs):
            raise OSError("anchor unavailable")

        monkeypatch.setattr(repository.anchor_store, "write", unavailable)
        repository.append_audit(admin(), "backlog.probe", "test", "one", {"probe": True})
        response = client.get("/ready")
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["pending_anchor_events"] == 1
        assert detail["outbox_within_budget"] is False


def test_migration_mode_refuses_unversioned_schema(tmp_path: Path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'unversioned.db'}",
        schema_mode="auto",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="schema-audit-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
    )
    app = create_app(settings)
    with TestClient(app):
        pass
    migration_settings = settings.model_copy(update={"schema_mode": "migrations"})
    migration_app = create_app(migration_settings)
    try:
        with TestClient(migration_app):
            raise AssertionError("migration mode accepted a schema without Alembic revision")
    except RuntimeError as exc:
        assert "schema revision mismatch" in str(exc)


def test_controlled_environment_rejects_sqlite_and_missing_anchor_auth(tmp_path: Path):
    import pytest

    calibration = write_calibration_bundle(tmp_path)
    base = dict(
        environment="production",
        schema_mode="migrations",
        object_store_mode="s3",
        s3_bucket="korpus",
        s3_governance_retention_days=30,
        auth_mode="oidc",
        oidc_jwks_url="https://id.example/jwks",
        jwt_issuer="https://id.example",
        audit_hmac_key="a" * 40,
        audit_anchor_mode="http",
        audit_anchor_url="https://anchor.example/v1/head",
        answer_policy_mode="calibrated",
        **calibration,
        review_separation_required=True,
        metrics_token="metrics-token",
        cors_origins="https://korpus.example",
        **controlled_security_kwargs(tmp_path),
    )
    with pytest.raises(ValueError, match="require PostgreSQL"):
        Settings(
            database_url=f"sqlite:///{tmp_path / 'bad.db'}", audit_anchor_token="token", **base
        )
    with pytest.raises(ValueError, match="anchor authentication"):
        Settings(database_url="postgresql+psycopg://u:p@db/korpus?sslmode=verify-full", **base)


def test_semantic_configuration_cannot_drift_from_calibration(tmp_path: Path):
    import pytest
    calibration = write_calibration_bundle(tmp_path, weight_semantic=0.0)
    with pytest.raises(ValueError, match="calibration assigns zero semantic weight"):
        Settings(
            environment="test",
            database_url="postgresql+psycopg://u:p@db/korpus?sslmode=verify-full",
            semantic_retrieval_enabled=True,
            semantic_weight=0.1,
            embedding_endpoint="http://127.0.0.1:9009/embed",
            embedding_model_id="test-model",
            answer_policy_mode="calibrated",
            **calibration,
        )


def test_backup_crypto_roundtrip_and_tamper_detection(tmp_path: Path):
    from cryptography.exceptions import InvalidTag

    from scripts.backup_crypto import decrypt, encrypt, load_key

    key_path = tmp_path / "key.hex"
    key_path.write_text("ab" * 32)
    source = tmp_path / "source.dump"
    source.write_bytes((b"korpus-backup-block\n" * 100_000) + b"tail")
    encrypted = tmp_path / "backup.dump.enc"
    restored = tmp_path / "restored.dump"
    key = load_key(key_path)
    encrypt(source, encrypted, key)
    decrypt(encrypted, restored, key)
    assert restored.read_bytes() == source.read_bytes()

    payload = bytearray(encrypted.read_bytes())
    payload[len(payload) // 2] ^= 0x01
    tampered = tmp_path / "tampered.dump.enc"
    tampered.write_bytes(payload)
    with pytest.raises(InvalidTag):
        decrypt(tampered, tmp_path / "must-not-exist.dump", key)
    assert not (tmp_path / "must-not-exist.dump").exists()


def test_readiness_rejects_validly_signed_anchor_on_wrong_history(client, admin_identity):
    import json

    repository = client.app.state.repository
    repository.append_audit(admin_identity, "history.probe", "test", "one", {"probe": True})
    path = repository.anchor_store.path
    forged = repository.anchor_store.codec.encode(1, "f" * 64)
    path.write_text(json.dumps(forged), encoding="utf-8")
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["anchor_matches_history"] is False


def test_readiness_rejects_anchor_reset_without_replayable_outbox(client, admin_identity):
    repository = client.app.state.repository
    repository.append_audit(admin_identity, "anchor.reset.probe", "test", "one", {"probe": True})
    assert repository.verify_audit().valid is True
    repository.anchor_store.reset()
    response = client.get("/ready")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["anchor_gap_events"] == 1
    assert detail["anchor_gap_recoverable"] is False


def test_unknown_environment_cannot_bypass_controlled_profile():
    with pytest.raises(ValueError, match="environment must be one of"):
        Settings(environment="prodution")


def test_controlled_database_requires_server_identity_verification(tmp_path: Path):
    calibration = write_calibration_bundle(tmp_path)
    with pytest.raises(ValueError, match="sslmode=verify-full"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://u:p@db/korpus?sslmode=require",
            schema_mode="migrations",
            object_store_mode="s3",
            s3_bucket="korpus",
            s3_governance_retention_days=30,
            auth_mode="oidc",
            oidc_jwks_url="https://id.example/jwks",
            jwt_issuer="https://id.example/",
            audit_hmac_key="a" * 40,
            audit_anchor_mode="http",
            audit_anchor_url="https://anchor.example/v1/head",
            audit_anchor_token="anchor-token",
            answer_policy_mode="calibrated",
            **calibration,
            review_separation_required=True,
            metrics_token="metrics-token",
            cors_origins="https://korpus.example",
        )


def test_reconcile_failures_are_observable():
    from korpus.infrastructure.observability import Observability

    observability = Observability()
    observability.observe_anchor_reconcile_failure(TimeoutError("anchor timeout"))
    exported = observability.export_prometheus().decode("utf-8")
    metric = 'korpus_audit_anchor_reconcile_failures_total{error_class="TimeoutError"} 1.0'
    assert metric in exported
    observability.close()


def test_backup_restore_scripts_are_cwd_independent_and_key_bound(tmp_path: Path):
    import json
    import os

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pg_dump = bin_dir / "pg_dump"
    # This double used to accept --file=- and treat it as "write to stdout", which is
    # what the backup script passed and what nobody had ever checked against a real
    # pg_dump. On PostgreSQL 17 that flag produced an empty stdout — the first real
    # run of this job encrypted zero bytes — so the double was certifying a pipeline
    # that could not work. It now behaves like the tool: no --file means stdout, and
    # --file=<path> writes there. Passing --file=- would write a file named "-".
    pg_dump.write_text(
        """#!/usr/bin/env python3
import pathlib, sys
payload = b'PGDMP\\x01korpus-infra-test'
target = next((value for value in sys.argv[1:] if value.startswith('--file=')), None)
if target is None:
    sys.stdout.buffer.write(payload)
else:
    pathlib.Path(target.split('=', 1)[1]).write_bytes(payload)
""",
        encoding="utf-8",
    )
    pg_restore = bin_dir / "pg_restore"
    pg_restore.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    # This double printed the literal "ok" — the answer the old restore check looked
    # for, not anything a database would say. The check itself compared against a
    # hardcoded '0003_infrastructure_hardening', so from migration 0004 onward it
    # could only ever fail, and it failed through `grep -q`, which prints nothing.
    # The double now answers with the real head, read from the migration files, so
    # the test exercises the comparison instead of pre-agreeing with it.
    psql = bin_dir / "psql"
    psql.write_text(
        "#!/usr/bin/env python3\n"
        "import ast, pathlib, sys\n"
        f"versions = pathlib.Path({str(ROOT / 'apps/api/migrations/versions')!r})\n"
        "revisions, parents = set(), set()\n"
        "for path in sorted(versions.glob('*.py')):\n"
        "    for node in ast.parse(path.read_text(encoding='utf-8')).body:\n"
        "        target = None\n"
        "        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):\n"
        "            target = node.target.id\n"
        "        elif isinstance(node, ast.Assign) and len(node.targets) == 1:\n"
        "            first = node.targets[0]\n"
        "            target = first.id if isinstance(first, ast.Name) else None\n"
        "        value = getattr(node, 'value', None)\n"
        "        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):\n"
        "            continue\n"
        "        if target == 'revision':\n"
        "            revisions.add(value.value)\n"
        "        elif target == 'down_revision':\n"
        "            parents.add(value.value)\n"
        "print(sorted(revisions - parents)[0])\n",
        encoding="utf-8",
    )
    for executable in (pg_dump, pg_restore, psql):
        executable.chmod(0o755)

    key = tmp_path / "backup.key"
    key.write_text("ab" * 32, encoding="ascii")
    backup_dir = tmp_path / "backups"
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "KORPUS_BACKUP_DATABASE_URL": "postgresql://test.invalid/korpus",
        "KORPUS_BACKUP_ENCRYPTION_KEY_FILE": str(key),
        "KORPUS_BACKUP_KEY_ID": "test-key-v1",
        "KORPUS_BACKUP_DIR": str(backup_dir),
    }
    completed = subprocess.run(
        [str(ROOT / "scripts/backup_postgres.sh")],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    backup = Path(completed.stdout.strip())
    manifest = json.loads(Path(f"{backup}.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "korpus-postgres-backup-v4"
    assert manifest["key_id"] == "test-key-v1"
    assert manifest["file"] == backup.name
    assert manifest["bytes"] == backup.stat().st_size
    assert len(manifest["manifest_hmac_sha256"]) == 64
    assert manifest["plaintext_bytes"] == len(b"PGDMP\x01korpus-infra-test")

    restore_environment = {
        **environment,
        "KORPUS_RESTORE_DATABASE_URL": "postgresql://test.invalid/restored",
    }
    restored = subprocess.run(
        [str(ROOT / "scripts/restore_postgres.sh"), str(backup)],
        cwd=tmp_path,
        env=restore_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert "test-key-v1" in restored.stderr

    tampered_manifest_path = Path(f"{backup}.json")
    original_manifest = tampered_manifest_path.read_text(encoding="utf-8")
    tampered_manifest = json.loads(original_manifest)
    tampered_manifest["plaintext_bytes"] += 1
    tampered_manifest_path.write_text(json.dumps(tampered_manifest), encoding="utf-8")
    tampered = subprocess.run(
        [str(ROOT / "scripts/restore_postgres.sh"), str(backup)],
        cwd=tmp_path,
        env=restore_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert tampered.returncode == 65
    assert "manifest verification failed" in tampered.stderr
    tampered_manifest_path.write_text(original_manifest, encoding="utf-8")

    restore_environment["KORPUS_BACKUP_KEY_ID"] = "wrong-key"
    rejected = subprocess.run(
        [str(ROOT / "scripts/restore_postgres.sh"), str(backup)],
        cwd=tmp_path,
        env=restore_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 65
    assert "key id mismatch" in rejected.stderr
