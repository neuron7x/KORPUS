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
    evidence = {
        "source_tree_sha256": compute_source_digest(ROOT),
        "release": release_tag(),
        "environment_class": "PRODUCTION_LIKE",
        "preregistration_sha256": hashlib.sha256(tevv_gate.PROFILE.read_bytes()).hexdigest(),
        "corpus": {"corpus_id": "declared", "owner": "test", "document_set_sha256": "a" * 64, "synthetic": False},
        "observations": 260,
        "passed": 260,
        "citation_failures": 0,
        "leakage_failures": 0,
        "determinism_failures": 0,
        "null_controls": 49,
        "null_control_false_accepts": 0,
        "attack_families": profile["required_attack_families"],
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
