from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from backup_crypto import load_key  # noqa: E402
from backup_manifest import sign  # noqa: E402
from postgres_live_assurance import (  # noqa: E402
    backup_receipt,
    optional_duration,
    pytest_receipt,
)
from validate_postgres_assurance import validate_payload  # noqa: E402


def write_backup_fixture(tmp_path: Path) -> tuple[Path, Path]:
    backup = tmp_path / "fixture.dump.enc"
    backup.write_bytes(b"authenticated-ciphertext-fixture")
    key_file = tmp_path / "key"
    key_file.write_text("01" * 32, encoding="ascii")
    payload: dict[str, object] = {
        "schema": "korpus-postgres-backup-v4",
        "created_at": "20260801T000000.000000Z",
        "encrypted": True,
        "cipher": "AES-256-GCM",
        "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
        "bytes": backup.stat().st_size,
        "plaintext_sha256": hashlib.sha256(b"plaintext").hexdigest(),
        "plaintext_bytes": 9,
        "file": backup.name,
        "key_id": "test-key",
    }
    payload["manifest_hmac_sha256"] = sign(payload, load_key(key_file))
    Path(f"{backup}.json").write_text(json.dumps(payload), encoding="utf-8")
    return backup, key_file


def test_backup_receipt_is_derived_from_authenticated_artifact(tmp_path: Path) -> None:
    backup, key_file = write_backup_fixture(tmp_path)
    receipt = backup_receipt(backup, key_file, "test-key")
    assert receipt["manifest_verified"] is True
    assert receipt["encrypted_sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()


def test_backup_receipt_rejects_ciphertext_tampering(tmp_path: Path) -> None:
    backup, key_file = write_backup_fixture(tmp_path)
    backup.write_bytes(backup.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="checksum|size"):
        backup_receipt(backup, key_file, "test-key")


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        ('tests="2" failures="0" errors="0" skipped="0"', "PASS"),
        ('tests="2" failures="1" errors="0" skipped="0"', "FAIL"),
        ('tests="0" failures="0" errors="0" skipped="0"', "FAIL"),
    ],
)
def test_pytest_receipt_fails_closed(
    tmp_path: Path, attributes: str, expected: str
) -> None:
    path = tmp_path / "junit.xml"
    path.write_text(f"<testsuite {attributes}/>", encoding="utf-8")
    assert pytest_receipt(path)["live_postgres"] == expected


def test_missing_duration_is_unavailable_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KORPUS_BACKUP_SECONDS", raising=False)
    assert optional_duration("KORPUS_BACKUP_SECONDS") is None


def test_nonpositive_duration_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KORPUS_BACKUP_SECONDS", "0")
    with pytest.raises(ValueError, match="must be positive"):
        optional_duration("KORPUS_BACKUP_SECONDS")


def valid_assurance_payload() -> dict[str, object]:
    payload = {name: {} for name in __import__("validate_postgres_assurance").REQUIRED}
    payload.update(
        {
            "verdict": "PASS_WITH_CAVEATS",
            "production_authorized": False,
            "application_role_properties": {
                name: False
                for name in (
                    "rolsuper",
                    "rolbypassrls",
                    "rolcreatedb",
                    "rolcreaterole",
                    "rolinherit",
                )
            },
            "alembic_expected_heads": ["head"],
            "source_database_revision": ["head"],
            "restored_database_revision": ["head"],
            "rls_cases": {"missing_context_counts": {"documents": 0}},
            "ddl_denial_cases": {"alembic_update": "PASS", "privileged_ddl": "PASS"},
            "backup": {
                "encrypted": True,
                "manifest_verified": True,
                "cipher": "AES-256-GCM",
            },
            "pytest": {"live_postgres": "PASS"},
            "source_state_digest": "digest",
            "restored_state_digest": "digest",
        }
    )
    return payload


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (lambda value: value["backup"].update(manifest_verified=False), "predicate:backup"),
        (lambda value: value["pytest"].update(live_postgres="UNAVAILABLE"), "predicate:pytest"),
        (lambda value: value.update(restored_state_digest="different"), "predicate:state-digest"),
        (
            lambda value: value["application_role_properties"].update(rolbypassrls=True),
            "predicate:application-role",
        ),
    ],
)
def test_validator_rejects_manufactured_pass(mutate, failure: str) -> None:
    payload = valid_assurance_payload()
    mutate(payload)
    assert failure in validate_payload(payload)
