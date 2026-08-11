from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import run_tevv_production_gate as tevv_gate  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402


def _evidence() -> tuple[dict, bytes]:
    profile = json.loads(tevv_gate.PROFILE.read_text(encoding="utf-8"))
    required = profile["required_attack_families"]
    observations = [
        {
            "id": f"obs-{index}", "passed": True,
            "citation_failures": 0, "leakage_failures": 0, "determinism_failures": 0,
            "attack_families": [required[index % len(required)]],
        }
        for index in range(260)
    ]
    evidence = {
        "schema": profile["evidence_schema"],
        "source_tree_sha256": compute_source_digest(ROOT),
        "release": release_tag(),
        "environment_class": "PRODUCTION_LIKE",
        "preregistration_sha256": hashlib.sha256(tevv_gate.PROFILE.read_bytes()).hexdigest(),
        "corpus": {"corpus_id": "declared", "owner": "test", "document_set_sha256": "a" * 64, "synthetic": False},
        "observation_ledger": observations,
        "null_control_ledger": [{"id": f"null-{index}", "false_accept": False} for index in range(49)],
    }
    data = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    return evidence, data


def _attest(data: bytes) -> tuple[dict, str]:
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    fingerprint = hashlib.sha256(public).hexdigest()
    return {
        "algorithm": "Ed25519", "release": release_tag(), "manifest": "tevv-evidence.json",
        "manifest_sha256": hashlib.sha256(data).hexdigest(), "public_key_pem": public.decode(),
        "public_key_sha256": fingerprint, "signature_base64": base64.b64encode(key.sign(data)).decode(),
    }, fingerprint


def test_production_like_string_without_trusted_attestation_does_not_pass_tevv_gate() -> None:
    profile = json.loads(tevv_gate.PROFILE.read_text(encoding="utf-8"))
    evidence, data = _evidence()
    attestation, _ = _attest(data)
    result = tevv_gate.evaluate(evidence, profile, attestation, set(), data, "tevv-evidence.json")
    assert result["checks"]["environment_class"] is True
    assert result["checks"]["environment_attestation_verified"] is True
    assert result["checks"]["environment_trusted_signer"] is False
    assert result["status"] == "FAIL"


def test_pretrusted_signed_production_like_tevv_evidence_can_clear_environment_boundary() -> None:
    profile = json.loads(tevv_gate.PROFILE.read_text(encoding="utf-8"))
    evidence, data = _evidence()
    attestation, fingerprint = _attest(data)
    result = tevv_gate.evaluate(evidence, profile, attestation, {fingerprint}, data, "tevv-evidence.json")
    assert result["status"] == "PASS", result


def _trusted_result(evidence: dict) -> dict:
    profile = json.loads(tevv_gate.PROFILE.read_text(encoding="utf-8"))
    data = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    attestation, fingerprint = _attest(data)
    return tevv_gate.evaluate(evidence, profile, attestation, {fingerprint}, data, "tevv-evidence.json")


def test_trusted_aggregate_only_tevv_summary_cannot_replace_case_ledger() -> None:
    evidence, _ = _evidence()
    evidence.pop("observation_ledger")
    evidence.pop("null_control_ledger")
    evidence.update({
        "observations": 1000, "passed": 1000,
        "citation_failures": 0, "leakage_failures": 0, "determinism_failures": 0,
        "null_controls": 100, "null_control_false_accepts": 0,
        "attack_families": json.loads(tevv_gate.PROFILE.read_text())["required_attack_families"],
    })
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
