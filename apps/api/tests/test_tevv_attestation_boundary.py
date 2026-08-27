from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import run_tevv_production_gate as tevv_gate  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402


def _gold_bytes(evidence: dict) -> bytes:
    receipt = {
        "schema": "korpus.gold-annotation-admission.v1",
        "status": "PASS",
        "bindings": {
            "source_tree_sha256": compute_source_digest(ROOT),
            "release": release_tag(),
            "corpus_release_sha256": evidence["corpus"]["document_set_sha256"],
            "model_id": evidence["model_id"],
            "configuration_sha256": evidence["configuration_sha256"],
        },
    }
    return (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode()


def _evidence() -> tuple[dict, bytes]:
    profile = json.loads(tevv_gate.PROFILE.read_text(encoding="utf-8"))
    required = profile["required_attack_families"]
    cohorts = profile["required_cohorts"]
    observations = [
        {
            "id": f"obs-{index}",
            "passed": True,
            "citation_failures": 0,
            "leakage_failures": 0,
            "determinism_failures": 0,
            "attack_families": [required[index % len(required)]],
            "cohorts": [cohorts[index % len(cohorts)]],
        }
        for index in range(260)
    ]
    evidence = {
        "schema": profile["evidence_schema"],
        "source_tree_sha256": compute_source_digest(ROOT),
        "release": release_tag(),
        "environment_class": "PRODUCTION_LIKE",
        "evidence_class": "EXTERNAL_INDEPENDENT",
        "model_id": "embedding-model-v1",
        "configuration_sha256": "c" * 64,
        "assessor": {
            "organization": "independent-test-lab",
            "assessor_id": "assessor-1",
            "independent_of_system_owner": True,
        },
        "preregistration_sha256": hashlib.sha256(tevv_gate.PROFILE.read_bytes()).hexdigest(),
        "corpus": {
            "corpus_id": "declared",
            "owner": "test",
            "document_set_sha256": "a" * 64,
            "synthetic": False,
        },
        "deployment_context_sha256": "b" * 64,
        "evaluation_cues_blinded": True,
        "simulated_dependency_failures": profile["required_simulated_dependency_failures"],
        "observation_ledger": observations,
        "null_control_ledger": [
            {"id": f"null-{index}", "false_accept": False} for index in range(49)
        ],
    }
    evidence["gold_annotation_receipt_sha256"] = hashlib.sha256(_gold_bytes(evidence)).hexdigest()
    data = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    return evidence, data


def _attest(data: bytes) -> tuple[dict, str]:
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    fingerprint = hashlib.sha256(public).hexdigest()
    return {
        "algorithm": "Ed25519",
        "release": release_tag(),
        "manifest": "tevv-evidence.json",
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
        "public_key_pem": public.decode(),
        "public_key_sha256": fingerprint,
        "signature_base64": base64.b64encode(key.sign(data)).decode(),
    }, fingerprint


def test_production_like_string_without_trusted_attestation_does_not_pass_tevv_gate() -> None:
    profile = json.loads(tevv_gate.PROFILE.read_text(encoding="utf-8"))
    evidence, data = _evidence()
    attestation, _ = _attest(data)
    gold = _gold_bytes(evidence)
    result = tevv_gate.evaluate(
        evidence, profile, attestation, set(), data, "tevv-evidence.json", json.loads(gold), gold
    )
    assert result["checks"]["environment_class"] is True
    assert result["checks"]["assessor_attestation_verified"] is True
    assert result["checks"]["assessor_trusted_signer"] is False
    assert result["status"] == "FAIL"


def test_pretrusted_signed_production_like_tevv_evidence_can_clear_environment_boundary() -> None:
    profile = json.loads(tevv_gate.PROFILE.read_text(encoding="utf-8"))
    evidence, data = _evidence()
    attestation, fingerprint = _attest(data)
    gold = _gold_bytes(evidence)
    result = tevv_gate.evaluate(
        evidence,
        profile,
        attestation,
        {fingerprint},
        data,
        "tevv-evidence.json",
        json.loads(gold),
        gold,
    )
    assert result["status"] == "PASS", result


def test_trusted_static_benchmark_without_deployment_simulation_fails() -> None:
    evidence, _ = _evidence()
    evidence.pop("deployment_context_sha256")
    evidence["evaluation_cues_blinded"] = False
    evidence["simulated_dependency_failures"] = []

    result = _trusted_result(evidence)

    assert result["checks"]["deployment_context_bound"] is False
    assert result["checks"]["evaluation_cues_blinded"] is False
    assert result["checks"]["dependency_failures_simulated"] is False


def _trusted_result(evidence: dict) -> dict:
    profile = json.loads(tevv_gate.PROFILE.read_text(encoding="utf-8"))
    data = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    attestation, fingerprint = _attest(data)
    gold = _gold_bytes(evidence)
    return tevv_gate.evaluate(
        evidence,
        profile,
        attestation,
        {fingerprint},
        data,
        "tevv-evidence.json",
        json.loads(gold),
        gold,
    )


def test_gold_receipt_bytes_and_exact_system_bindings_are_mandatory() -> None:
    evidence, _ = _evidence()
    profile = json.loads(tevv_gate.PROFILE.read_text(encoding="utf-8"))
    data = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    attestation, fingerprint = _attest(data)

    missing = tevv_gate.evaluate(
        evidence, profile, attestation, {fingerprint}, data, "tevv-evidence.json", {}, b""
    )
    gold = _gold_bytes(evidence)
    receipt = json.loads(gold)
    receipt["bindings"]["model_id"] = "different-model"
    wrong_model = tevv_gate.evaluate(
        evidence,
        profile,
        attestation,
        {fingerprint},
        data,
        "tevv-evidence.json",
        receipt,
        gold,
    )

    assert missing["checks"]["gold_receipt_present"] is False
    assert wrong_model["checks"]["gold_receipt_system_bound"] is False


def test_trusted_aggregate_only_tevv_summary_cannot_replace_case_ledger() -> None:
    evidence, _ = _evidence()
    evidence.pop("observation_ledger")
    evidence.pop("null_control_ledger")
    evidence.update(
        {
            "observations": 1000,
            "passed": 1000,
            "citation_failures": 0,
            "leakage_failures": 0,
            "determinism_failures": 0,
            "null_controls": 100,
            "null_control_false_accepts": 0,
            "attack_families": json.loads(tevv_gate.PROFILE.read_text())[
                "required_attack_families"
            ],
        }
    )
    result = _trusted_result(evidence)
    assert result["status"] == "FAIL"
    assert result["checks"]["observation_ledger_structured"] is False


def test_trusted_tevv_ledger_must_cover_required_attack_families() -> None:
    evidence, _ = _evidence()
    required = json.loads(tevv_gate.PROFILE.read_text())["required_attack_families"]
    missing = required[-1]
    for row in evidence["observation_ledger"]:
        if missing in row["attack_families"]:
            row["attack_families"] = [required[0]]
    result = _trusted_result(evidence)
    assert result["status"] == "FAIL"
    assert result["checks"]["required_attack_families_covered"] is False


def test_trusted_tevv_summary_cannot_hide_ledger_leakage_failure() -> None:
    evidence, _ = _evidence()
    evidence["observation_ledger"][0]["leakage_failures"] = 1
    evidence["leakage_failures"] = 0
    result = _trusted_result(evidence)
    assert result["status"] == "FAIL"
    assert result["checks"]["leakage"] is False
    assert result["checks"]["declared_aggregates_consistent"] is False


def test_trusted_tevv_summary_cannot_hide_null_false_accept() -> None:
    evidence, _ = _evidence()
    evidence["null_control_ledger"][0]["false_accept"] = True
    evidence["null_control_false_accepts"] = 0
    result = _trusted_result(evidence)
    assert result["status"] == "FAIL"
    assert result["checks"]["null_false_accepts"] is False
    assert result["checks"]["declared_aggregates_consistent"] is False


def test_trusted_tevv_duplicate_observation_ids_fail_closed() -> None:
    evidence, _ = _evidence()
    evidence["observation_ledger"][1]["id"] = evidence["observation_ledger"][0]["id"]
    result = _trusted_result(evidence)
    assert result["status"] == "FAIL"
    assert result["checks"]["observation_ids_unique"] is False


def test_trusted_tevv_wrong_evidence_schema_fails_closed() -> None:
    evidence, _ = _evidence()
    evidence["schema"] = "korpus.tevv-evidence.v1"
    result = _trusted_result(evidence)
    assert result["status"] == "FAIL"
    assert result["checks"]["evidence_schema"] is False


def test_trusted_tevv_without_independent_class_fails_closed() -> None:
    evidence, _ = _evidence()
    evidence["evidence_class"] = "INTERNAL"
    result = _trusted_result(evidence)
    assert result["status"] == "FAIL"
    assert result["checks"]["independent_class"] is False


def test_trusted_tevv_without_independent_assessor_identity_fails_closed() -> None:
    evidence, _ = _evidence()
    evidence["assessor"] = {
        "organization": "owner",
        "assessor_id": "same-party",
        "independent_of_system_owner": False,
    }
    result = _trusted_result(evidence)
    assert result["status"] == "FAIL"
    assert result["checks"]["assessor_structured"] is False


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("minimum_observations", True),
        ("minimum_observations", 1.5),
        ("minimum_observations", "1"),
        ("minimum_null_controls", True),
        ("minimum_null_controls", 1.5),
        ("minimum_null_controls", "1"),
        ("minimum_pass_rate", False),
        ("minimum_pass_rate", "1.0"),
        ("maximum_interval_width", "0.1"),
        ("maximum_citation_failures", False),
    ],
)
def test_tevv_policy_does_not_coerce_malformed_numeric_thresholds(field: str, bad: object) -> None:
    profile = json.loads(tevv_gate.PROFILE.read_text(encoding="utf-8"))
    profile[field] = bad
    evidence, data = _evidence()
    attestation, fingerprint = _attest(data)
    with pytest.raises(ValueError):
        tevv_gate.evaluate(
            evidence, profile, attestation, {fingerprint}, data, "tevv-evidence.json", {}, b""
        )
