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
    candidate_commit,
    optional_duration,
    pytest_receipt,
    mutation_receipt,
    security_predicates_pass,
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
        ('tests="2" failures="0" errors="0" skipped="1"', "FAIL"),
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


def test_mutation_receipt_requires_every_valid_mutant_to_be_killed(tmp_path: Path) -> None:
    path = tmp_path / "mutation.json"
    payload = {
        "candidate_commit": "a" * 40,
        "mutation_score": 1.0,
        "mutants": 3,
        "valid_mutants": 3,
        "killed": 3,
        "survived": [],
        "invalid": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert mutation_receipt(path, "a" * 40)["status"] == "PASS"
    with pytest.raises(ValueError, match="candidate"):
        mutation_receipt(path, "b" * 40)
    payload["invalid"] = ["M03"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="complete mutant killing"):
        mutation_receipt(path, "a" * 40)


def test_candidate_commit_uses_explicit_ci_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = "a" * 40
    monkeypatch.setenv("KORPUS_CANDIDATE_COMMIT", expected)
    monkeypatch.setattr(
        "postgres_live_assurance.subprocess.check_output",
        lambda *args, **kwargs: pytest.fail("Git must not be invoked"),
    )
    assert candidate_commit() == expected


def test_candidate_commit_rejects_unverifiable_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KORPUS_CANDIDATE_COMMIT", "HEAD")
    with pytest.raises(ValueError, match="full lowercase Git SHA-1"):
        candidate_commit()


def test_security_predicates_require_force_rls_and_compartment_isolation() -> None:
    role = {
        name: False
        for name in (
            "rolsuper",
            "rolbypassrls",
            "rolcreatedb",
            "rolcreaterole",
            "rolinherit",
            "schema_create",
            "database_create",
        )
    }
    role["governed_table_ownership_count"] = 0
    policies = [
        {
            "tablename": name,
            "cmd": "SELECT",
            "rls_enabled": True,
            "force_rls": True,
        }
        for name in (
            "documents",
            "document_versions",
            "evidence_spans",
            "span_embeddings",
            "document_compartments",
        )
    ]
    compartments = {"missing": 0, "unrelated": 0, "exact": 1}
    assert security_predicates_pass(role, compartments, policies, 1, 0) is True
    policies[0]["force_rls"] = False
    assert security_predicates_pass(role, compartments, policies, 1, 0) is False
    policies[0]["force_rls"] = True
    assert security_predicates_pass(
        role, {"missing": 1, "unrelated": 0, "exact": 1}, policies, 1, 0
    ) is False


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
                    "schema_create",
                    "database_create",
                )
            },
            "schema": "korpus.postgres-live-assurance.v1",
            "act_id": "KORPUS-ACT-01",
            "base_commit": "a" * 40,
            "candidate_commit": "b" * 40,
            "alembic_expected_heads": ["head"],
            "source_database_revision": ["head"],
            "restored_database_revision": ["head"],
            "rls_cases": {
                "missing_context_counts": {
                    name: 0
                    for name in (
                        "documents",
                        "document_versions",
                        "evidence_spans",
                        "span_embeddings",
                        "document_compartments",
                    )
                },
                "public_identity_public_rows": 1,
                "public_identity_restricted_rows": 0,
                "cross_corpus_direct_sql_restricted_rows": 1,
            },
            "compartment_cases": {"missing": 0, "unrelated": 0, "exact": 1},
            "table_policy_inventory": [
                {
                    "schemaname": "public",
                    "tablename": name,
                    "cmd": "SELECT",
                    "rls_enabled": True,
                    "force_rls": True,
                }
                for name in (
                    "documents",
                    "document_versions",
                    "evidence_spans",
                    "span_embeddings",
                    "document_compartments",
                )
            ],
            "grant_inventory": [
                {"table_name": "alembic_version", "privilege_type": "SELECT"}
            ],
            "ddl_denial_cases": {
                name: "PASS"
                for name in (
                    "alembic_update",
                    "create_table",
                    "alter_table",
                    "drop_table",
                    "create_policy",
                    "create_schema",
                    "create_extension",
                    "create_role",
                    "alter_role",
                    "set_role",
                )
            },
            "backup": {
                "encrypted": True,
                "manifest_verified": True,
                "cipher": "AES-256-GCM",
                "duration_seconds": 1.0,
            },
            "restore": {
                "duration_seconds": 2.0,
                "verification_seconds": 3.0,
                "total_recovery_seconds": 6.0,
                "measurement": "ANCHORED",
            },
            "pytest": {
                "live_postgres": "PASS",
                "tests": 1,
                "failures": 0,
                "errors": 0,
                "skipped": 0,
            },
            "mutation": {
                "status": "PASS",
                "mutants": 29,
                "killed": 29,
                "candidate_commit": "b" * 40,
                "sha256": "d" * 64,
            },
            "source_state_digest": "c" * 64,
            "restored_state_digest": "c" * 64,
            "iam_006_probe": {
                "status": "CONFIRMED_OPEN",
                "broadened_restricted_rows": 1,
                "trust_anchor_independent_of_application": False,
            },
        }
    )
    payload["application_role_properties"]["governed_table_ownership_count"] = 0
    return payload


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (lambda value: value["backup"].update(manifest_verified=False), "predicate:backup"),
        (lambda value: value["pytest"].update(live_postgres="UNAVAILABLE"), "predicate:pytest"),
        (lambda value: value["pytest"].update(skipped=1), "predicate:pytest"),
        (lambda value: value.update(restored_state_digest="different"), "predicate:state-digest"),
        (
            lambda value: value["restore"].update(total_recovery_seconds=5.0),
            "predicate:recovery-timing",
        ),
        (
            lambda value: value["application_role_properties"].update(rolbypassrls=True),
            "predicate:application-role",
        ),
        (
            lambda value: value["ddl_denial_cases"].pop("set_role"),
            "predicate:ddl-denial",
        ),
        (
            lambda value: value.update(compartment_cases={"missing": 1, "unrelated": 0, "exact": 1}),
            "predicate:compartment-isolation",
        ),
        (
            lambda value: value["rls_cases"].update(
                public_identity_restricted_rows=1
            ),
            "predicate:cross-corpus",
        ),
        (
            lambda value: value["table_policy_inventory"][0].update(force_rls=False),
            "predicate:policy-inventory",
        ),
        (
            lambda value: value["grant_inventory"].append(
                {"table_name": "alembic_version", "privilege_type": "UPDATE"}
            ),
            "predicate:grant-inventory",
        ),
        (
            lambda value: value["iam_006_probe"].update(
                status="NOT_REPRODUCED", broadened_restricted_rows=1
            ),
            "predicate:iam-006",
        ),
    ],
)
def test_validator_rejects_manufactured_pass(mutate, failure: str) -> None:
    payload = valid_assurance_payload()
    mutate(payload)
    assert failure in validate_payload(payload)
